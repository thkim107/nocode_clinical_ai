"""Structured PostgreSQL telemetry for paper-ready usage and latency metrics.

The generic audit log remains available for operational tracing.  This module
adds correlated sessions, workflow runs, LLM calls, tool calls and external
API calls without storing raw prompts, clinical text or tool results.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Optional

logger = logging.getLogger("telemetry")

DATABASE_URL = os.getenv("AUDIT_DB_URL", "")
APP_VERSION = os.getenv("APP_VERSION", os.getenv("IMAGE_TAG", "unknown"))
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "unknown")
PROMPT_LANG = os.getenv("PROMPT_LANG", "en")
HMAC_KEY = os.getenv("TELEMETRY_HMAC_KEY", "")


@dataclass(frozen=True)
class TraceContext:
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    subject_id: Optional[str] = None
    module: Optional[str] = None
    operation: Optional[str] = None
    section: Optional[str] = None


_context: ContextVar[TraceContext] = ContextVar("telemetry_context", default=TraceContext())


def current_context() -> TraceContext:
    return _context.get()


def set_context(**values: Any):
    """Bind telemetry identifiers; return a token that must be reset."""
    return _context.set(replace(_context.get(), **values))


def reset_context(token) -> None:
    _context.reset(token)


def _uuid(value: Optional[str]) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return str(uuid.uuid4())


def _subject_id(user_code: str) -> Optional[str]:
    if not user_code or not HMAC_KEY:
        return None
    return hmac.new(HMAC_KEY.encode(), user_code.encode(), hashlib.sha256).hexdigest()


def _json(value: Any, max_chars: int = 16000) -> Optional[str]:
    if value is None:
        return None
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        serialized = json.dumps({"repr": repr(value)[:2000]})
    if len(serialized) <= max_chars:
        return serialized
    return json.dumps({
        "truncated": True,
        "original_chars": len(serialized),
        "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "preview": serialized[: max_chars - 500],
    }, ensure_ascii=False)


def summarize_payload(value: Any) -> dict[str, Any]:
    """Return a non-content summary suitable for clinical/research payloads."""
    serialized = json.dumps(value, ensure_ascii=False, default=str)
    summary: dict[str, Any] = {
        "chars": len(serialized),
        "bytes": len(serialized.encode("utf-8")),
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    }
    if isinstance(value, dict):
        summary["keys"] = sorted(str(k) for k in value.keys())[:100]
    elif isinstance(value, list):
        summary["items"] = len(value)
    return summary


_async_pool = None
_async_retry_after = 0.0


async def _get_async_pool():
    global _async_pool, _async_retry_after
    if _async_pool is not None or not DATABASE_URL:
        return _async_pool
    if time.monotonic() < _async_retry_after:
        return None
    try:
        import asyncpg
        _async_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=8)
    except Exception as exc:
        _async_retry_after = time.monotonic() + 30
        logger.warning("telemetry database unavailable; retrying in 30s: %s", exc)
    return _async_pool


async def _execute(sql: str, *args: Any) -> bool:
    pool = await _get_async_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as connection:
            await connection.execute(sql, *args)
        return True
    except Exception as exc:
        logger.warning("telemetry insert failed: %s", exc)
        return False


async def query_rows(sql: str, *args: Any) -> list[dict[str, Any]]:
    """Execute a read-only dashboard query or report database unavailability."""
    statement = sql.lstrip().upper()
    if not statement.startswith(("SELECT", "WITH")):
        raise ValueError("Telemetry dashboard queries must be read-only")
    pool = await _get_async_pool()
    if pool is None:
        raise RuntimeError("Telemetry database is unavailable")
    try:
        async with pool.acquire() as connection:
            records = await connection.fetch(sql, *args)
        return [dict(record) for record in records]
    except Exception as exc:
        logger.warning("telemetry query failed: %s", exc)
        raise RuntimeError("Telemetry query failed") from exc


_sync_pool = None
_sync_retry_after = 0.0
_sync_lock = threading.Lock()


def _get_sync_pool():
    global _sync_pool, _sync_retry_after
    if _sync_pool is not None or not DATABASE_URL:
        return _sync_pool
    if time.monotonic() < _sync_retry_after:
        return None
    with _sync_lock:
        if _sync_pool is not None:
            return _sync_pool
        try:
            from psycopg2.pool import ThreadedConnectionPool
            _sync_pool = ThreadedConnectionPool(1, 20, DATABASE_URL, connect_timeout=3)
        except Exception as exc:
            _sync_retry_after = time.monotonic() + 30
            logger.warning("telemetry sync database unavailable; retrying in 30s: %s", exc)
    return _sync_pool


def _execute_sync(sql: str, args: tuple[Any, ...]) -> bool:
    pool = _get_sync_pool()
    if pool is None:
        return False
    connection = None
    try:
        connection = pool.getconn()
        with connection.cursor() as cursor:
            cursor.execute(sql, args)
        connection.commit()
        return True
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        logger.warning("telemetry sync insert failed: %s", exc)
        return False
    finally:
        if connection is not None:
            pool.putconn(connection)


def _classify_path(path: str) -> tuple[str, str, Optional[str]]:
    operation = path.removeprefix("/api/").strip("/") or "root"
    section = None
    if path.startswith("/api/chat"):
        module = "chat"
    elif path.startswith("/api/research/pubmed_search"):
        module = "pubmed"
    elif path.startswith("/api/research/research_plan"):
        module = "planner" if "/v2/" in path else "irb_document"
    elif path.startswith("/api/research"):
        module = "research"
    elif path.startswith("/api/"):
        module = "files"
    else:
        module = "platform"
    return module, operation, section


async def begin_workflow(
    *, session_id: str, run_id: str, subject_id: Optional[str], module: str,
    operation: str, section: Optional[str], method: str, path: str,
) -> None:
    await _execute(
        """
        INSERT INTO telemetry.sessions
            (session_id, subject_id, app_version, prompt_version, prompt_lang)
        VALUES ($1::uuid, $2, $3, $4, $5)
        ON CONFLICT (session_id) DO UPDATE
        SET last_seen_at = now(), subject_id = COALESCE(telemetry.sessions.subject_id, EXCLUDED.subject_id)
        """,
        session_id, subject_id, APP_VERSION, PROMPT_VERSION, PROMPT_LANG,
    )
    await _execute(
        """
        INSERT INTO telemetry.workflow_runs
            (run_id, session_id, module, operation, section, status, http_method, path)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, 'running', $6, $7)
        ON CONFLICT (run_id) DO UPDATE
        SET status = 'running', completed_at = NULL, duration_ms = NULL,
            last_segment_at = now(), module = EXCLUDED.module,
            operation = COALESCE(telemetry.workflow_runs.operation, EXCLUDED.operation)
        """,
        run_id, session_id, module, operation, section, method, path,
    )


async def finish_workflow(run_id: str, *, status: str, http_status: Optional[int], error: Optional[str] = None) -> None:
    await _execute(
        """
        UPDATE telemetry.workflow_runs
        SET status = CASE
                WHEN status <> 'running' AND $2 = 'succeeded' THEN status
                ELSE $2
            END,
            http_status = $3,
            completed_at = now(),
            duration_ms = (EXTRACT(EPOCH FROM (clock_timestamp() - started_at)) * 1000)::bigint,
            error = $4
        WHERE run_id = $1::uuid
        """,
        run_id, status, http_status, (error or None) and error[:4000],
    )


async def set_workflow_status(status: str, *, metadata: Any = None) -> None:
    ctx = current_context()
    if not ctx.run_id:
        return
    await _execute(
        """
        UPDATE telemetry.workflow_runs
        SET status = $2, metadata = metadata || COALESCE($3::jsonb, '{}'::jsonb),
            last_segment_at = now()
        WHERE run_id = $1::uuid
        """,
        ctx.run_id, status, _json(metadata),
    )


async def record_event(
    event_type: str, *, phase: Optional[str] = None, section: Optional[str] = None,
    attempt: Optional[int] = None, metadata: Any = None,
) -> None:
    ctx = current_context()
    await _execute(
        """
        INSERT INTO telemetry.workflow_events
            (run_id, session_id, module, operation, section, event_type, phase, attempt, metadata)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb)
        """,
        ctx.run_id, ctx.session_id, ctx.module, ctx.operation, section or ctx.section,
        event_type, phase, attempt, _json(metadata or {}),
    )


def record_event_sync(
    event_type: str, *, phase: Optional[str] = None, section: Optional[str] = None,
    attempt: Optional[int] = None, metadata: Any = None,
) -> None:
    ctx = current_context()
    _execute_sync(
        """
        INSERT INTO telemetry.workflow_events
            (run_id, session_id, module, operation, section, event_type, phase, attempt, metadata)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (ctx.run_id, ctx.session_id, ctx.module, ctx.operation, section or ctx.section,
         event_type, phase, attempt, _json(metadata or {})),
    )


async def record_llm_call(
    *, call_id: str, provider: str, model: str, duration_ms: int,
    input_tokens: Optional[int], output_tokens: Optional[int], total_tokens: Optional[int],
    cached_input_tokens: Optional[int] = None, reasoning_tokens: Optional[int] = None,
    token_source: str = "provider", finish_reason: Optional[str] = None,
    request_chars: Optional[int] = None, response_chars: Optional[int] = None,
    message_count: Optional[int] = None,
    tool_definition_count: Optional[int] = None, iteration: Optional[int] = None,
    attempt: Optional[int] = None, status: str = "succeeded", error: Optional[str] = None,
    operation: Optional[str] = None, section: Optional[str] = None, metadata: Any = None,
) -> None:
    ctx = current_context()
    await _execute(
        """
        INSERT INTO telemetry.llm_calls
            (call_id, run_id, session_id, module, operation, section, iteration, attempt,
             provider, model, duration_ms, input_tokens, output_tokens, total_tokens,
             cached_input_tokens, reasoning_tokens, token_source, finish_reason,
             request_chars, response_chars, message_count, tool_definition_count,
             status, error, metadata)
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13, $14, $15, $16, $17, $18,
                $19, $20, $21, $22, $23, $24, $25::jsonb)
        """,
        call_id, ctx.run_id, ctx.session_id, ctx.module, operation or ctx.operation,
        section or ctx.section, iteration, attempt, provider, model, duration_ms,
        input_tokens, output_tokens, total_tokens, cached_input_tokens, reasoning_tokens,
        token_source, finish_reason, request_chars, response_chars, message_count,
        tool_definition_count, status, (error or None) and error[:4000],
        _json(metadata or {}),
    )


def record_llm_call_sync(**values: Any) -> None:
    ctx = current_context()
    _execute_sync(
        """
        INSERT INTO telemetry.llm_calls
            (call_id, run_id, session_id, module, operation, section, iteration, attempt,
             provider, model, duration_ms, input_tokens, output_tokens, total_tokens,
             cached_input_tokens, reasoning_tokens, token_source, finish_reason,
             request_chars, response_chars, message_count, tool_definition_count,
             status, error, metadata)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            values.get("call_id", str(uuid.uuid4())), ctx.run_id, ctx.session_id, ctx.module,
            values.get("operation") or ctx.operation, values.get("section") or ctx.section,
            values.get("iteration"), values.get("attempt"), values.get("provider"),
            values.get("model"), values.get("duration_ms"), values.get("input_tokens"),
            values.get("output_tokens"), values.get("total_tokens"),
            values.get("cached_input_tokens"), values.get("reasoning_tokens"),
            values.get("token_source", "provider"), values.get("finish_reason"),
            values.get("request_chars"), values.get("response_chars"),
            values.get("message_count"),
            values.get("tool_definition_count"), values.get("status", "succeeded"),
            (values.get("error") or None) and str(values.get("error"))[:4000],
            _json(values.get("metadata") or {}),
        ),
    )


async def record_tool_requested(
    *, provider_tool_call_id: str, llm_call_id: Optional[str], server: str,
    tool_name: str, iteration: int, approval_mode: str, tool_input: Any,
) -> None:
    ctx = current_context()
    await _execute(
        """
        INSERT INTO telemetry.tool_calls
            (run_id, session_id, llm_call_id, provider_tool_call_id, module, iteration,
             server, tool_name, approval_mode, status, input_summary)
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, 'requested', $10::jsonb)
        ON CONFLICT (run_id, provider_tool_call_id) DO UPDATE
        SET approval_mode = EXCLUDED.approval_mode, input_summary = EXCLUDED.input_summary
        """,
        ctx.run_id, ctx.session_id, llm_call_id, provider_tool_call_id, ctx.module,
        iteration, server, tool_name, approval_mode, _json(summarize_payload(tool_input)),
    )


async def mark_tool_approved(provider_tool_call_id: str) -> None:
    ctx = current_context()
    await _execute(
        """
        UPDATE telemetry.tool_calls
        SET approved_at = now(), status = 'approved',
            approval_wait_ms = (EXTRACT(EPOCH FROM (clock_timestamp() - requested_at)) * 1000)::bigint
        WHERE run_id = $1::uuid AND provider_tool_call_id = $2
        """,
        ctx.run_id, provider_tool_call_id,
    )


async def complete_tool_call(
    provider_tool_call_id: str, *, duration_ms: int, success: bool,
    output: Any = None, error: Optional[str] = None,
) -> None:
    ctx = current_context()
    await _execute(
        """
        UPDATE telemetry.tool_calls
        SET started_at = COALESCE(
                started_at,
                clock_timestamp() - ($3::bigint * interval '1 millisecond')
            ),
            completed_at = now(), duration_ms = $3::bigint,
            status = $4, output_summary = $5::jsonb, error = $6
        WHERE run_id = $1::uuid AND provider_tool_call_id = $2
        """,
        ctx.run_id, provider_tool_call_id, duration_ms,
        "succeeded" if success else "failed", _json(summarize_payload(output)),
        (error or None) and error[:4000],
    )


async def deny_tool_calls(provider_tool_call_ids: list[str]) -> None:
    ctx = current_context()
    await _execute(
        """
        UPDATE telemetry.tool_calls
        SET status = 'denied', completed_at = now(),
            approval_wait_ms = (EXTRACT(EPOCH FROM (clock_timestamp() - requested_at)) * 1000)::bigint
        WHERE run_id = $1::uuid AND provider_tool_call_id = ANY($2::text[])
        """,
        ctx.run_id, provider_tool_call_ids,
    )
    await set_workflow_status("denied", metadata={"denied_tool_count": len(provider_tool_call_ids)})


def record_external_call_sync(
    *, service: str, operation: str, duration_ms: int, status_code: Optional[int],
    result_count: Optional[int] = None, success: bool = True, error: Optional[str] = None,
    metadata: Any = None,
) -> None:
    ctx = current_context()
    _execute_sync(
        """
        INSERT INTO telemetry.external_calls
            (run_id, session_id, module, service, operation, duration_ms, status_code,
             result_count, status, error, metadata)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (ctx.run_id, ctx.session_id, ctx.module, service, operation, duration_ms,
         status_code, result_count, "succeeded" if success else "failed",
         (error or None) and error[:4000], _json(metadata or {})),
    )


class TelemetryMiddleware:
    """Correlate every API response, including streaming responses, with a run."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not path.startswith("/api/")
            or path.startswith("/api/telemetry")
            or path in ("/api/ls", "/api/chat/tools")
            or path.startswith("/api/research/session/")
            or (scope.get("method") == "GET" and path.startswith("/api/research/llm/"))
        ):
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        session_id = _uuid(headers.get("x-session-id"))
        run_id = _uuid(headers.get("x-run-id"))
        subject_id = _subject_id(headers.get("x-user-code", ""))
        module, operation, section = _classify_path(scope["path"])
        token = set_context(
            session_id=session_id, run_id=run_id, subject_id=subject_id,
            module=module, operation=operation, section=section,
        )
        response_status = 500
        completed = False

        await begin_workflow(
            session_id=session_id, run_id=run_id, subject_id=subject_id,
            module=module, operation=operation, section=section,
            method=scope.get("method", ""), path=scope["path"],
        )

        async def send_wrapper(message):
            nonlocal response_status, completed
            if message["type"] == "http.response.start":
                response_status = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.extend([
                    (b"x-session-id", session_id.encode()),
                    (b"x-run-id", run_id.encode()),
                ])
                message["headers"] = response_headers
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
                status = "succeeded" if response_status < 400 else "failed"
                await finish_workflow(run_id, status=status, http_status=response_status)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            await finish_workflow(run_id, status="cancelled", http_status=response_status, error="client disconnected")
            raise
        except Exception as exc:
            await finish_workflow(run_id, status="failed", http_status=response_status, error=str(exc))
            raise
        finally:
            if not completed:
                await finish_workflow(run_id, status="cancelled", http_status=response_status, error="response did not complete")
            reset_context(token)
