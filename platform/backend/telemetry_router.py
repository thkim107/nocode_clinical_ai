"""Token-protected, read-only telemetry dashboard and CSV exports."""

from __future__ import annotations

import asyncio
import csv
import hmac
import io
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from telemetry import query_rows as telemetry_query_rows

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
MAX_CSV_ROWS = 100_000
MAX_TIMELINE_ITEMS_PER_TYPE = 500

# Keep automated page hydration and polling out of the human-readable activity view.
# The raw reports and CSV exports below still expose the complete research dataset.
ACTIVE_RUN_SQL = "(r.http_method IN ('POST', 'PUT', 'PATCH', 'DELETE') OR r.path = '/api/download')"


def require_viewer_token(x_telemetry_token: str = Header(default="")) -> None:
    """Keep research telemetry and CSV exports out of the public application UI."""
    expected = os.getenv("TELEMETRY_VIEWER_TOKEN", "")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telemetry viewer is not configured",
        )
    if not x_telemetry_token or not hmac.compare_digest(x_telemetry_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid telemetry viewer token",
            headers={"WWW-Authenticate": "TelemetryToken"},
        )


router = APIRouter(
    prefix="/api/telemetry",
    tags=["telemetry"],
    dependencies=[Depends(require_viewer_token)],
)


@dataclass(frozen=True)
class Report:
    select_sql: str
    from_sql: str
    date_column: str
    order_sql: str


REPORT_COLUMNS: dict[str, tuple[str, ...]] = {
    "sessions": (
        "session_id", "subject_id", "started_at", "last_seen_at", "app_version",
        "prompt_version", "prompt_lang", "workflow_runs", "successful_runs",
        "unsuccessful_runs", "workflow_duration_ms", "llm_calls", "input_tokens",
        "output_tokens", "total_tokens", "llm_compute_ms", "tool_calls",
        "successful_tool_calls", "manual_tool_calls", "auto_tool_calls",
        "tool_compute_ms", "approval_wait_ms",
    ),
    "runs": (
        "run_id", "session_id", "module", "operation", "section", "status",
        "started_at", "completed_at", "wall_duration_ms", "llm_calls",
        "failed_llm_calls", "input_tokens", "output_tokens", "total_tokens",
        "llm_compute_ms", "tool_calls", "failed_tool_calls", "manual_tool_calls",
        "denied_tool_calls", "tool_compute_ms", "approval_wait_ms", "external_calls",
        "failed_external_calls", "external_compute_ms", "external_result_count",
    ),
    "llm_calls": (
        "call_id", "run_id", "session_id", "module", "operation", "section",
        "iteration", "attempt", "provider", "model", "started_at", "duration_ms",
        "input_tokens", "output_tokens", "total_tokens", "cached_input_tokens",
        "reasoning_tokens", "token_source", "request_chars", "response_chars",
        "message_count", "tool_definition_count", "status", "finish_reason", "has_error",
    ),
    "tool_calls": (
        "id", "run_id", "session_id", "provider_tool_call_id", "module", "iteration",
        "server", "tool_name", "approval_mode", "status", "requested_at", "approved_at",
        "started_at", "completed_at", "approval_wait_ms", "duration_ms", "input_chars",
        "input_bytes", "output_chars", "output_bytes", "has_error",
    ),
    "external_calls": (
        "id", "run_id", "session_id", "module", "service", "operation", "started_at",
        "duration_ms", "status_code", "result_count", "status", "has_error", "metadata",
    ),
    "events": (
        "id", "run_id", "session_id", "module", "operation", "section", "event_type",
        "phase", "attempt", "ts", "metadata",
    ),
}


REPORTS: dict[str, Report] = {
    "sessions": Report(
        select_sql="""
            SELECT session_id::text AS session_id, subject_id, started_at, last_seen_at,
                   app_version, prompt_version, prompt_lang, workflow_runs,
                   successful_runs, unsuccessful_runs, workflow_duration_ms,
                   llm_calls, input_tokens, output_tokens, total_tokens,
                   llm_compute_ms, tool_calls, successful_tool_calls,
                   manual_tool_calls, auto_tool_calls, tool_compute_ms,
                   approval_wait_ms
        """,
        from_sql="FROM paper_metrics.session_summary",
        date_column="started_at",
        order_sql="started_at DESC",
    ),
    "runs": Report(
        select_sql="""
            SELECT run_id::text AS run_id, session_id::text AS session_id,
                   module, operation, section, status, started_at, completed_at,
                   wall_duration_ms, llm_calls, failed_llm_calls,
                   input_tokens, output_tokens, total_tokens, llm_compute_ms,
                   tool_calls, failed_tool_calls, manual_tool_calls,
                   denied_tool_calls, tool_compute_ms, approval_wait_ms,
                   external_calls, failed_external_calls, external_compute_ms,
                   external_result_count
        """,
        from_sql="FROM paper_metrics.run_summary",
        date_column="started_at",
        order_sql="started_at DESC",
    ),
    "llm_calls": Report(
        select_sql="""
            SELECT call_id::text AS call_id, run_id::text AS run_id,
                   session_id::text AS session_id, module, operation, section,
                   iteration, attempt, provider, model, started_at, duration_ms,
                   input_tokens, output_tokens, total_tokens,
                   cached_input_tokens, reasoning_tokens, token_source,
                   request_chars, response_chars, message_count,
                   tool_definition_count, status, finish_reason,
                   (error IS NOT NULL) AS has_error
        """,
        from_sql="FROM telemetry.llm_calls",
        date_column="started_at",
        order_sql="started_at DESC",
    ),
    "tool_calls": Report(
        select_sql="""
            SELECT id, run_id::text AS run_id, session_id::text AS session_id,
                   provider_tool_call_id, module, iteration, server, tool_name,
                   approval_mode, status, requested_at, approved_at, started_at,
                   completed_at, approval_wait_ms, duration_ms,
                   input_summary->>'chars' AS input_chars,
                   input_summary->>'bytes' AS input_bytes,
                   output_summary->>'chars' AS output_chars,
                   output_summary->>'bytes' AS output_bytes,
                   (error IS NOT NULL) AS has_error
        """,
        from_sql="FROM telemetry.tool_calls",
        date_column="requested_at",
        order_sql="requested_at DESC",
    ),
    "external_calls": Report(
        select_sql="""
            SELECT id, run_id::text AS run_id, session_id::text AS session_id,
                   module, service, operation, started_at, duration_ms,
                   status_code, result_count, status,
                   (error IS NOT NULL) AS has_error,
                   metadata::text AS metadata
        """,
        from_sql="FROM telemetry.external_calls",
        date_column="started_at",
        order_sql="started_at DESC",
    ),
    "events": Report(
        select_sql="""
            SELECT id, run_id::text AS run_id, session_id::text AS session_id,
                   module, operation, section, event_type, phase, attempt, ts,
                   metadata::text AS metadata
        """,
        from_sql="FROM telemetry.workflow_events",
        date_column="ts",
        order_sql="ts DESC",
    ),
}


# These downloads mirror the human-readable activity view: only user-initiated
# work within the selected period, with one row per task or session.
SUMMARY_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "runs": (
        ("session_id", "세션 ID"), ("run_id", "작업 ID"),
        ("subject_id", "가명 사용자"), ("module_label", "탭"),
        ("operation_label", "작업 내용"), ("section", "섹션"),
        ("status_label", "상태"), ("started_at", "시작 시각"),
        ("completed_at", "종료 시각"), ("wall_seconds", "작업 시간(초)"),
        ("llm_calls", "모델 호출 수"), ("input_tokens", "입력 토큰"),
        ("output_tokens", "출력 토큰"), ("total_tokens", "전체 토큰"),
        ("tool_calls", "도구 호출 수"), ("manual_tool_calls", "수동 승인 도구 수"),
        ("denied_tool_calls", "거절된 도구 수"),
        ("approval_wait_seconds", "승인 대기(초)"),
        ("external_calls", "외부 API 호출 수"),
    ),
    "sessions": (
        ("session_id", "세션 ID"), ("subject_id", "가명 사용자"),
        ("first_at", "첫 작업 시각"), ("last_at", "마지막 작업 시각"),
        ("work_count", "작업 수"), ("successful_runs", "완료 작업 수"),
        ("unsuccessful_runs", "실패·취소 작업 수"),
        ("work_seconds", "작업 시간 합계(초)"),
        ("mean_work_seconds", "평균 작업 시간(초)"),
        ("llm_calls", "모델 호출 수"), ("input_tokens", "입력 토큰"),
        ("output_tokens", "출력 토큰"), ("total_tokens", "전체 토큰"),
        ("tool_calls", "도구 호출 수"), ("manual_tool_calls", "수동 승인 도구 수"),
        ("denied_tool_calls", "거절된 도구 수"),
        ("approval_wait_seconds", "승인 대기 합계(초)"),
        ("external_calls", "외부 API 호출 수"),
    ),
}

MODULE_LABELS = {
    "chat": "채팅", "planner": "연구 계획", "pubmed": "PubMed",
    "irb_document": "연구 문서", "research": "연구 설정", "files": "파일",
}
OPERATION_LABELS = {
    "chat/completions": "채팅 답변 생성",
    "chat/approve-tools": "채팅 도구 승인 후 계속",
    "chat/deny-tools": "채팅 도구 사용 거절",
    "research/pubmed_search": "PubMed 논문 검색·평가",
    "research/research_plan/v2/topic/refine": "연구 주제 정제",
    "research/research_plan/v2/questions/generate": "연구 질문 생성",
    "research/research_plan/v2/sections/generate_chain": "연구 계획 6개 섹션 생성",
    "research/research_plan/v2/sections/revise": "연구 계획 섹션 수정",
    "research/research_plan/v2/docs/revise": "연구 문서 수정",
    "research/research_plan/get_research_background_answer": "연구 배경 질문 생성",
    "research/research_plan/get_background_build_answer": "연구 배경 작성",
    "research/research_plan/get_hypothesis": "연구 가설 작성",
    "research/research_plan/check_data_analysis": "분석 방법 질문 생성",
    "research/research_plan/get_data_analysis": "데이터 분석 방법 작성",
    "upload": "파일 업로드", "mkdir": "폴더 생성",
    "delete": "파일 삭제", "download": "파일 다운로드",
}
STATUS_LABELS = {
    "succeeded": "완료", "failed": "실패", "cancelled": "취소",
    "denied": "거절", "limit_reached": "반복 제한",
    "waiting_approval": "승인 대기", "running": "진행 중",
}


async def _query_rows(sql: str, *args: Any) -> list[dict[str, Any]]:
    try:
        return await telemetry_query_rows(sql, *args)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _report_or_404(report_name: str) -> Report:
    report = REPORTS.get(report_name)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Unknown telemetry report: {report_name}")
    return report


def _where(report: Report) -> str:
    return f"WHERE ($1::int = 0 OR {report.date_column} >= now() - make_interval(days => $1::int))"


def _display_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        text = value.isoformat()
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    # Prevent spreadsheet formula execution when opened in Excel.
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.get("/overview")
async def get_overview(days: int = Query(30, ge=0, le=3650)):
    rows = await _query_rows(
        """
        WITH filtered_runs AS (
            SELECT * FROM telemetry.workflow_runs
            WHERE ($1::int = 0 OR started_at >= now() - make_interval(days => $1::int))
              AND (http_method IN ('POST', 'PUT', 'PATCH', 'DELETE') OR path = '/api/download')
        ), background_runs AS (
            SELECT count(*) AS n FROM telemetry.workflow_runs
            WHERE ($1::int = 0 OR started_at >= now() - make_interval(days => $1::int))
              AND NOT (http_method IN ('POST', 'PUT', 'PATCH', 'DELETE') OR path = '/api/download')
        ), filtered_llm AS (
            SELECT * FROM telemetry.llm_calls
            WHERE ($1::int = 0 OR started_at >= now() - make_interval(days => $1::int))
        ), filtered_tools AS (
            SELECT * FROM telemetry.tool_calls
            WHERE ($1::int = 0 OR requested_at >= now() - make_interval(days => $1::int))
        ), filtered_external AS (
            SELECT * FROM telemetry.external_calls
            WHERE ($1::int = 0 OR started_at >= now() - make_interval(days => $1::int))
        )
        SELECT
            (SELECT count(DISTINCT session_id) FROM filtered_runs) AS sessions,
            (SELECT count(*) FROM filtered_runs) AS runs,
            (SELECT n FROM background_runs) AS background_requests,
            (SELECT count(*) FROM filtered_runs WHERE status = 'succeeded') AS successful_runs,
            (SELECT count(*) FROM filtered_runs WHERE status = 'waiting_approval') AS waiting_runs,
            (SELECT count(*) FROM filtered_runs
             WHERE status IN ('failed', 'cancelled', 'denied', 'limit_reached')) AS unsuccessful_runs,
            (SELECT avg(duration_ms)::bigint FROM filtered_runs WHERE completed_at IS NOT NULL) AS mean_wall_ms,
            (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms)
             FROM filtered_runs WHERE completed_at IS NOT NULL) AS median_wall_ms,
            (SELECT count(*) FROM filtered_llm) AS llm_calls,
            (SELECT count(*) FROM filtered_llm WHERE status = 'failed') AS failed_llm_calls,
            (SELECT sum(input_tokens) FROM filtered_llm) AS input_tokens,
            (SELECT sum(output_tokens) FROM filtered_llm) AS output_tokens,
            (SELECT sum(total_tokens) FROM filtered_llm) AS total_tokens,
            (SELECT sum(duration_ms) FROM filtered_llm) AS llm_compute_ms,
            (SELECT count(*) FROM filtered_tools) AS tool_calls,
            (SELECT count(*) FROM filtered_tools WHERE status = 'failed') AS failed_tool_calls,
            (SELECT count(*) FROM filtered_tools WHERE status = 'denied') AS denied_tool_calls,
            (SELECT count(*) FROM filtered_tools WHERE approval_mode = 'manual') AS manual_tool_calls,
            (SELECT avg(approval_wait_ms)::bigint FROM filtered_tools
             WHERE approval_wait_ms IS NOT NULL) AS mean_approval_wait_ms,
            (SELECT sum(duration_ms) FROM filtered_tools) AS tool_compute_ms,
            (SELECT count(*) FROM filtered_external) AS external_calls,
            (SELECT count(*) FROM filtered_external WHERE status = 'failed') AS failed_external_calls
        """,
        days,
    )
    return jsonable_encoder(rows[0] if rows else {})


@router.get("/activity")
async def get_activity(
    days: int = Query(30, ge=0, le=3650),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session_id: UUID | None = None,
    module: str = Query("", max_length=40),
):
    """Show user-initiated work with its linked model/tool counts."""
    where_sql = (
        f"WHERE {ACTIVE_RUN_SQL} "
        "AND ($1::int = 0 OR r.started_at >= now() - make_interval(days => $1::int)) "
        "AND ($2::uuid IS NULL OR r.session_id = $2::uuid) "
        "AND ($3::text = '' OR r.module = $3::text)"
    )
    args = (days, str(session_id) if session_id else None, module)
    rows, count_rows = await asyncio.gather(
        _query_rows(
            "SELECT summary.*, s.subject_id "
            "FROM paper_metrics.run_summary summary "
            "JOIN telemetry.workflow_runs r USING (run_id) "
            "LEFT JOIN telemetry.sessions s ON s.session_id = r.session_id "
            f"{where_sql} ORDER BY r.started_at DESC, r.run_id DESC "
            "LIMIT $4::int OFFSET $5::int",
            *args, limit, offset,
        ),
        _query_rows(
            f"SELECT count(*) AS total FROM telemetry.workflow_runs r {where_sql}",
            *args,
        ),
    )
    return {
        "rows": jsonable_encoder(rows),
        "total": int(count_rows[0]["total"]),
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}/detail")
async def get_run_detail(run_id: UUID):
    """Return a chronological, bounded trace without raw prompts or tool payloads."""
    run_rows = await _query_rows(
        "SELECT summary.*, s.subject_id "
        "FROM paper_metrics.run_summary summary "
        "LEFT JOIN telemetry.sessions s ON s.session_id = summary.session_id "
        "WHERE summary.run_id = $1::uuid",
        str(run_id),
    )
    if not run_rows:
        raise HTTPException(status_code=404, detail="Telemetry run not found")

    llm, tools, external, events = await asyncio.gather(
        _query_rows(
            "SELECT call_id::text AS id, started_at AS at, section, iteration, attempt, "
            "provider, model, duration_ms, input_tokens, output_tokens, total_tokens, "
            "token_source, status, (error IS NOT NULL) AS has_error "
            "FROM telemetry.llm_calls WHERE run_id = $1::uuid "
            "ORDER BY started_at, call_id LIMIT $2::int",
            str(run_id), MAX_TIMELINE_ITEMS_PER_TYPE,
        ),
        _query_rows(
            "SELECT id::text, requested_at AS at, approved_at, started_at, completed_at, "
            "server, tool_name, iteration, approval_mode, approval_wait_ms, "
            "duration_ms, status, (error IS NOT NULL) AS has_error "
            "FROM telemetry.tool_calls WHERE run_id = $1::uuid "
            "ORDER BY requested_at, id LIMIT $2::int",
            str(run_id), MAX_TIMELINE_ITEMS_PER_TYPE,
        ),
        _query_rows(
            "SELECT id::text, started_at AS at, service, operation, duration_ms, "
            "status_code, result_count, status, (error IS NOT NULL) AS has_error "
            "FROM telemetry.external_calls WHERE run_id = $1::uuid "
            "ORDER BY started_at, id LIMIT $2::int",
            str(run_id), MAX_TIMELINE_ITEMS_PER_TYPE,
        ),
        _query_rows(
            "SELECT id::text, ts AS at, event_type, phase, section, attempt, "
            "metadata::text AS metadata "
            "FROM telemetry.workflow_events WHERE run_id = $1::uuid "
            "ORDER BY ts, id LIMIT $2::int",
            str(run_id), MAX_TIMELINE_ITEMS_PER_TYPE,
        ),
    )
    timeline = [
        {"kind": kind, **row}
        for kind, rows in (("llm", llm), ("tool", tools), ("external", external), ("event", events))
        for row in rows
    ]
    timeline.sort(key=lambda item: (item["at"], item["kind"], item["id"]))
    return {
        "run": jsonable_encoder(run_rows[0]),
        "timeline": jsonable_encoder(timeline),
        "timeline_truncated": any(
            len(rows) == MAX_TIMELINE_ITEMS_PER_TYPE
            for rows in (llm, tools, external, events)
        ),
    }


@router.get("/reports/{report_name}")
async def get_report(
    report_name: str,
    days: int = Query(30, ge=0, le=3650),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
):
    report = _report_or_404(report_name)
    where_sql = _where(report)
    rows = await _query_rows(
        f"{report.select_sql} {report.from_sql} {where_sql} "
        f"ORDER BY {report.order_sql} LIMIT $2::int OFFSET $3::int",
        days,
        limit,
        offset,
    )
    count_rows = await _query_rows(
        f"SELECT count(*) AS total {report.from_sql} {where_sql}",
        days,
    )
    total = int(count_rows[0]["total"]) if count_rows else 0
    columns = list(REPORT_COLUMNS[report_name])
    normalized = [
        {key: _display_value(value) for key, value in row.items()}
        for row in rows
    ]
    return {
        "report": report_name,
        "columns": columns,
        "rows": normalized,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/export/{report_name}.csv")
async def export_report_csv(
    report_name: str,
    days: int = Query(30, ge=0, le=3650),
):
    report = _report_or_404(report_name)
    rows = await _query_rows(
        f"{report.select_sql} {report.from_sql} {_where(report)} "
        f"ORDER BY {report.order_sql} LIMIT $2::int",
        days,
        MAX_CSV_ROWS,
    )

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    columns = list(REPORT_COLUMNS[report_name])
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_value(row.get(column)) for column in columns])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"telemetry_{report_name}_{timestamp}.csv"
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Rows": str(len(rows)),
            "X-Export-Row-Limit": str(MAX_CSV_ROWS),
        },
    )


@router.get("/export/summary/{kind}.csv")
async def export_summary_csv(
    kind: str,
    days: int = Query(30, ge=0, le=3650),
):
    """Download period-filtered task or session totals for spreadsheet analysis."""
    columns = SUMMARY_COLUMNS.get(kind)
    if columns is None:
        raise HTTPException(status_code=404, detail=f"Unknown telemetry summary: {kind}")

    selected_work = (
        "FROM paper_metrics.run_summary summary "
        "JOIN telemetry.workflow_runs r USING (run_id) "
        "LEFT JOIN telemetry.sessions session ON session.session_id = r.session_id "
        f"WHERE {ACTIVE_RUN_SQL} "
        "AND ($1::int = 0 OR r.started_at >= now() - make_interval(days => $1::int))"
    )
    if kind == "runs":
        sql = (
            "SELECT summary.session_id::text AS session_id, summary.run_id::text AS run_id, "
            "session.subject_id, summary.module, summary.operation, summary.section, "
            "summary.status, summary.started_at, summary.completed_at, "
            "round(summary.wall_duration_ms::numeric / 1000, 2) AS wall_seconds, "
            "summary.llm_calls, summary.input_tokens, summary.output_tokens, "
            "summary.total_tokens, summary.tool_calls, summary.manual_tool_calls, "
            "summary.denied_tool_calls, "
            "round(summary.approval_wait_ms::numeric / 1000, 2) AS approval_wait_seconds, "
            "summary.external_calls "
            f"{selected_work} "
            "ORDER BY r.started_at DESC, r.run_id DESC LIMIT $2::int"
        )
    else:
        sql = (
            "WITH selected AS ("
            "SELECT summary.*, r.started_at AS work_started_at, "
            "r.completed_at AS work_completed_at, session.subject_id "
            f"{selected_work}"
            ") SELECT session_id::text AS session_id, max(subject_id) AS subject_id, "
            "min(work_started_at) AS first_at, "
            "max(coalesce(work_completed_at, work_started_at)) AS last_at, "
            "count(*) AS work_count, "
            "count(*) FILTER (WHERE status = 'succeeded') AS successful_runs, "
            "count(*) FILTER (WHERE status IN ('failed','cancelled','denied','limit_reached')) "
            "AS unsuccessful_runs, "
            "round(coalesce(sum(wall_duration_ms),0)::numeric / 1000, 2) AS work_seconds, "
            "round(avg(wall_duration_ms)::numeric / 1000, 2) AS mean_work_seconds, "
            "coalesce(sum(llm_calls),0) AS llm_calls, "
            "coalesce(sum(input_tokens),0) AS input_tokens, "
            "coalesce(sum(output_tokens),0) AS output_tokens, "
            "coalesce(sum(total_tokens),0) AS total_tokens, "
            "coalesce(sum(tool_calls),0) AS tool_calls, "
            "coalesce(sum(manual_tool_calls),0) AS manual_tool_calls, "
            "coalesce(sum(denied_tool_calls),0) AS denied_tool_calls, "
            "round(coalesce(sum(approval_wait_ms),0)::numeric / 1000, 2) "
            "AS approval_wait_seconds, "
            "coalesce(sum(external_calls),0) AS external_calls "
            "FROM selected GROUP BY session_id "
            "ORDER BY max(work_started_at) DESC, session_id DESC LIMIT $2::int"
        )

    rows = await _query_rows(sql, days, MAX_CSV_ROWS)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([label for _, label in columns])
    for row in rows:
        if kind == "runs":
            module = str(row.get("module") or "")
            operation = str(row.get("operation") or "").rstrip("/")
            state = str(row.get("status") or "")
            row = {
                **row,
                "module_label": MODULE_LABELS.get(module, module),
                "operation_label": OPERATION_LABELS.get(operation, operation.replace("/", " › ")),
                "status_label": STATUS_LABELS.get(state, state),
            }
        writer.writerow([_csv_value(row.get(key)) for key, _ in columns])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"telemetry_summary_{kind}_{timestamp}.csv"
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Exported-Rows": str(len(rows)),
            "X-Export-Row-Limit": str(MAX_CSV_ROWS),
        },
    )
