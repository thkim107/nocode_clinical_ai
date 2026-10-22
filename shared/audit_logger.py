"""Audit logging shared by platform services.

Every outbound call (LLM, PubMed, MCP tool) is recorded in the ``audit_log``
table of the audit database (see ``init_audit_db.sql``).

Two entry points with the same signature:

* ``audit_log(...)``       - async, for use inside FastAPI handlers (asyncpg)
* ``audit_log_sync(...)``  - blocking, for code that runs in worker threads (psycopg2)

Both are fail-safe: if ``AUDIT_DB_URL`` is unset or the database is
unreachable, the event is logged to stdout at WARNING level and dropped.
Auditing must never break the request that triggered it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import threading
from typing import Any, Optional

logger = logging.getLogger("audit")

AUDIT_DB_URL = os.getenv("AUDIT_DB_URL", "")

_INSERT_SQL = """
INSERT INTO audit_log
    (source, target, endpoint, method, request_summary,
     response_status, response_summary, duration_ms, error)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""
_INSERT_SQL_PSYCOPG = _INSERT_SQL.replace("$1", "%s").replace("$2", "%s").replace("$3", "%s") \
    .replace("$4", "%s").replace("$5", "%s").replace("$6", "%s").replace("$7", "%s") \
    .replace("$8", "%s").replace("$9", "%s")


def _to_json(value: Any) -> Optional[str]:
    """Serialize a summary for a JSONB column; never raises."""
    if value is None:
        return None
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if len(serialized) <= 20000:
            return serialized
        # Keep the JSON valid. Cutting a serialized string in the middle makes
        # PostgreSQL reject the whole JSONB insert and loses the audit event.
        return json.dumps({
            "truncated": True,
            "original_chars": len(serialized),
            "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            "preview": serialized[:16000],
        }, ensure_ascii=False)
    except Exception:
        return json.dumps({"repr": repr(value)[:2000]})


def _fallback(source, target, endpoint, method, response_status, duration_ms, error, reason):
    logger.warning(
        "audit (not persisted: %s) %s -> %s %s %s status=%s %sms error=%s",
        reason, source, target, method, endpoint, response_status, duration_ms, error,
    )


# ----------------------------------------------------------------------------
# async (asyncpg)
# ----------------------------------------------------------------------------
_pool = None
_pool_retry_after = 0.0


async def _get_pool():
    global _pool, _pool_retry_after
    if _pool is not None or not AUDIT_DB_URL:
        return _pool
    if time.monotonic() < _pool_retry_after:
        return _pool
    try:
        import asyncpg  # imported lazily so sync-only services need not install it
        _pool = await asyncpg.create_pool(AUDIT_DB_URL, min_size=1, max_size=4)
    except Exception as e:  # pragma: no cover - environment dependent
        _pool_retry_after = time.monotonic() + 30
        logger.warning("audit db unavailable, retrying in 30s: %s", e)
    return _pool


async def audit_log(
    source: str,
    target: str,
    endpoint: str,
    method: str,
    *,
    request_summary: Any = None,
    response_status: Optional[int] = None,
    response_summary: Any = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    pool = await _get_pool()
    if pool is None:
        _fallback(source, target, endpoint, method, response_status, duration_ms, error,
                  "no AUDIT_DB_URL" if not AUDIT_DB_URL else "db unreachable")
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                _INSERT_SQL,
                source, target, endpoint, method,
                _to_json(request_summary), response_status, _to_json(response_summary),
                duration_ms, (error or None) and str(error)[:4000],
            )
    except Exception as e:
        _fallback(source, target, endpoint, method, response_status, duration_ms, error, f"insert failed: {e}")


# ----------------------------------------------------------------------------
# sync (psycopg2) - for code running in threads
# ----------------------------------------------------------------------------
_sync_pool = None
_sync_pool_retry_after = 0.0
_sync_pool_lock = threading.Lock()


def _get_sync_pool():
    global _sync_pool, _sync_pool_retry_after
    if _sync_pool is not None or not AUDIT_DB_URL:
        return _sync_pool
    if time.monotonic() < _sync_pool_retry_after:
        return None
    with _sync_pool_lock:
        if _sync_pool is not None:
            return _sync_pool
        try:
            from psycopg2.pool import ThreadedConnectionPool
            _sync_pool = ThreadedConnectionPool(1, 12, AUDIT_DB_URL, connect_timeout=3)
        except Exception as exc:
            _sync_pool_retry_after = time.monotonic() + 30
            logger.warning("audit sync db unavailable, retrying in 30s: %s", exc)
    return _sync_pool


def audit_log_sync(
    source: str,
    target: str,
    endpoint: str,
    method: str,
    *,
    request_summary: Any = None,
    response_status: Optional[int] = None,
    response_summary: Any = None,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    pool = _get_sync_pool()
    if pool is None:
        _fallback(
            source, target, endpoint, method, response_status, duration_ms, error,
            "no AUDIT_DB_URL" if not AUDIT_DB_URL else "db unreachable",
        )
        return
    connection = None
    try:
        connection = pool.getconn()
        with connection.cursor() as cursor:
            cursor.execute(
                _INSERT_SQL_PSYCOPG,
                (
                    source, target, endpoint, method,
                    _to_json(request_summary), response_status, _to_json(response_summary),
                    duration_ms, (error or None) and str(error)[:4000],
                ),
            )
        connection.commit()
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        _fallback(
            source, target, endpoint, method, response_status, duration_ms, error,
            f"insert failed: {exc}",
        )
    finally:
        if connection is not None:
            pool.putconn(connection)
