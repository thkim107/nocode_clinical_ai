import { useEffect, useState } from "react";
import {
  fetchTelemetryActivity,
  fetchTelemetryRunDetail,
  type TelemetryActivityResponse,
  type TelemetryRun,
  type TelemetryRunDetail,
  type TelemetryTimelineItem,
} from "../api/telemetry";

const OPERATION_NAMES: Record<string, string> = {
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
  "upload": "파일 업로드",
  "mkdir": "폴더 생성",
  "delete": "파일 삭제",
  "download": "파일 다운로드",
};

const MODULE_NAMES: Record<string, string> = {
  chat: "채팅", planner: "연구 계획", pubmed: "PubMed",
  irb_document: "연구 문서", research: "연구 설정", files: "파일",
};

const STATUS_NAMES: Record<string, string> = {
  succeeded: "완료", failed: "실패", cancelled: "취소", denied: "거절",
  limit_reached: "반복 제한", waiting_approval: "승인 대기", running: "진행 중",
  requested: "요청", approved: "승인",
};

const PHASE_NAMES: Record<string, string> = {
  "pubmed.search": "PubMed 검색",
  "pubmed.rule_filter": "규칙 기반 선별",
  "pubmed.relevance_filter": "LLM 관련성 선별",
  "pubmed.pimo_scoring": "PIMO 평가",
  "chat.tool_approval": "도구 승인",
  "chat.tool_loop": "도구 호출 반복",
  "chat.stream": "채팅 응답",
  "chat.approve_tools": "승인 후 채팅 응답",
};

const EVENT_NAMES: Record<string, string> = {
  phase_completed: "단계 완료", tool_approval_requested: "도구 승인 요청",
  tools_denied: "도구 사용 거절", max_tool_iterations: "도구 반복 제한",
  stream_failed: "응답 중 오류", llm_validation_failed: "모델 응답 검증 실패",
  section_quality_retry: "섹션 품질 재시도",
};

function count(value: unknown): string {
  return Number(value || 0).toLocaleString("ko-KR");
}

function elapsed(value: unknown): string {
  if (value == null) return "측정 중";
  const ms = Number(value);
  if (ms < 1000) return `${count(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}초`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)}분`;
  return `${(ms / 3_600_000).toFixed(1)}시간`;
}

function clock(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ko-KR");
}

function operationName(operation: string): string {
  return OPERATION_NAMES[operation.replace(/\/$/, "")] || operation.replace(/\//g, " › ");
}

function statusName(status: string): string {
  return STATUS_NAMES[status] || status;
}

function metadataSummary(value: unknown): string {
  if (typeof value !== "string") return "";
  try {
    const data = JSON.parse(value) as Record<string, unknown>;
    const labels: Record<string, string> = {
      query_count: "검색식", raw_hit_count: "검색 결과", unique_pmid_count: "고유 논문",
      input_count: "입력", passed_count: "통과", rejected_count: "제외",
      evaluation_count: "평가 대상", paper_count: "평가 논문",
      top_reference_count: "상위 참고문헌", llm_call_target_count: "예정 모델 호출",
    };
    return Object.entries(labels)
      .filter(([key]) => data[key] != null)
      .map(([key, label]) => `${label} ${count(data[key])}`)
      .join(" · ");
  } catch {
    return "";
  }
}

function timelineText(item: TelemetryTimelineItem): { title: string; detail: string } {
  if (item.kind === "llm") {
    const title = `모델 호출 · ${String(item.model || item.provider || "모델")}`;
    const tokens = item.total_tokens == null
      ? "토큰 수 미제공"
      : `입력 ${count(item.input_tokens)} · 출력 ${count(item.output_tokens)} 토큰`;
    return { title, detail: [item.section && `섹션 ${item.section}`, tokens,
      `소요 ${elapsed(item.duration_ms)}`, statusName(String(item.status || ""))].filter(Boolean).join(" · ") };
  }
  if (item.kind === "tool") {
    return {
      title: `도구 호출 · ${String(item.server || "")} / ${String(item.tool_name || "")}`,
      detail: [item.approval_mode === "manual" ? "수동 승인" : "자동 실행",
        item.approval_wait_ms != null && `승인 대기 ${elapsed(item.approval_wait_ms)}`,
        item.duration_ms != null && `실행 ${elapsed(item.duration_ms)}`,
        statusName(String(item.status || ""))].filter(Boolean).join(" · "),
    };
  }
  if (item.kind === "external") {
    return {
      title: `외부 API · ${String(item.service || "")} ${String(item.operation || "")}`,
      detail: [item.result_count != null && `결과 ${count(item.result_count)}건`,
        `소요 ${elapsed(item.duration_ms)}`, statusName(String(item.status || ""))].filter(Boolean).join(" · "),
    };
  }
  const phase = String(item.phase || "");
  return {
    title: `${EVENT_NAMES[String(item.event_type)] || String(item.event_type)}${phase ? ` · ${PHASE_NAMES[phase] || phase}` : ""}`,
    detail: [item.section && `섹션 ${item.section}`,
      item.attempt != null && `시도 ${item.attempt}회`, metadataSummary(item.metadata)].filter(Boolean).join(" · "),
  };
}

function RunDetail({ detail }: { detail: TelemetryRunDetail }) {
  const run = detail.run;
  return (
    <section className="telemetry-run-detail" aria-label="작업 상세">
      <h4>작업 흐름 · {operationName(run.operation)}</h4>
      <p className="telemetry-help">{clock(run.started_at)} 시작 → {clock(run.completed_at)} 종료 · 전체 {elapsed(run.wall_duration_ms)}</p>
      <div className="telemetry-detail-metrics">
        <span>모델 {count(run.llm_calls)}회 · 출력 {count(run.output_tokens)}토큰</span>
        <span>도구 {count(run.tool_calls)}회 · 승인 대기 {elapsed(run.approval_wait_ms ?? 0)}</span>
        <span>외부 API {count(run.external_calls)}회 · 결과 {count(run.external_result_count)}건</span>
      </div>
      <p className="telemetry-help">전체 시간은 요청 시작부터 종료까지입니다. 모델·도구·승인 시간은 겹칠 수 있어 합계와 일치하지 않을 수 있습니다.</p>
      <ol className="telemetry-timeline">
        <li><time>{clock(run.started_at)}</time><div><strong>작업 시작</strong><small>{operationName(run.operation)}</small></div></li>
        {detail.timeline.map((item) => {
          const content = timelineText(item);
          return (
            <li key={`${item.kind}-${item.id}`}>
              <time>{clock(item.at)}</time>
              <div><strong>{content.title}</strong><small>{content.detail}</small></div>
            </li>
          );
        })}
        {run.completed_at && <li><time>{clock(run.completed_at)}</time><div><strong>작업 {statusName(run.status)}</strong></div></li>}
      </ol>
      {detail.timeline_truncated && <p className="telemetry-help">호출 종류별 첫 500건까지만 표시합니다. 전체 기록은 아래 원본 로그에서 확인하세요.</p>}
      <p className="telemetry-help">프롬프트·답변·도구 입력/결과 원문은 개인정보 보호를 위해 기록하지 않아 이 화면에서 볼 수 없습니다.</p>
    </section>
  );
}

export default function TelemetryActivity({ token, days, onFailure }: {
  token: string;
  days: number;
  onFailure: (error: unknown) => void;
}) {
  const [activity, setActivity] = useState<TelemetryActivityResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [module, setModule] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [detail, setDetail] = useState<TelemetryRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const pageSize = 20;

  useEffect(() => {
    setOffset(0);
    setSelectedRunId("");
  }, [days]);

  useEffect(() => {
    let current = true;
    setLoading(true);
    fetchTelemetryActivity(token, days, pageSize, offset, sessionId, module)
      .then((data) => { if (current) setActivity(data); })
      .catch((error) => { if (current) onFailure(error); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [token, days, offset, sessionId, module, refreshKey, onFailure]);

  useEffect(() => {
    if (!selectedRunId) { setDetail(null); return; }
    let current = true;
    setDetail(null);
    setDetailLoading(true);
    fetchTelemetryRunDetail(token, selectedRunId)
      .then((data) => { if (current) setDetail(data); })
      .catch((error) => { if (current) onFailure(error); })
      .finally(() => { if (current) setDetailLoading(false); });
    return () => { current = false; };
  }, [token, selectedRunId, onFailure]);

  const chooseSession = (id: string) => {
    setSessionId(id);
    setOffset(0);
    setSelectedRunId("");
  };

  return (
    <section className="telemetry-activity">
      <div className="telemetry-section-heading">
        <div><h3>실제 작업 기록</h3><p>작업을 선택하면 모델 호출·도구 사용·연구 단계가 시간순으로 펼쳐집니다.</p></div>
        <button className="btn" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}>새로고침</button>
      </div>
      <div className="telemetry-activity-filters">
        <label>작업 종류
          <select value={module} onChange={(event) => { setModule(event.target.value); setOffset(0); setSelectedRunId(""); }}>
            <option value="">전체</option>
            {Object.entries(MODULE_NAMES).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
          </select>
        </label>
        {sessionId && <button className="btn btn-sm" onClick={() => chooseSession("")}>세션 필터 해제</button>}
        {sessionId && <span className="telemetry-session-filter" title={sessionId}>세션 {sessionId.slice(0, 8)}…</span>}
        <span>{count(activity?.total)}건</span>
      </div>
      {loading && <div className="loading-bar">작업 기록을 불러오는 중…</div>}
      {!loading && activity?.rows.length === 0 && (
        <div className="telemetry-empty">
          <strong>선택한 기간에 실제 작업 기록이 없습니다.</strong>
          <p>연구 계획 생성, PubMed 검색, 채팅 또는 도구 실행이 이루어지면 여기에 표시됩니다. 파일 목록 조회와 화면 복원 같은 자동 요청은 제외합니다.</p>
        </div>
      )}
      {!loading && activity?.rows.map((run: TelemetryRun) => (
        <article className="telemetry-run-card" key={run.run_id}>
          <button className="telemetry-run-main" onClick={() => setSelectedRunId(selectedRunId === run.run_id ? "" : run.run_id)} aria-expanded={selectedRunId === run.run_id}>
            <span className="telemetry-run-title"><strong>{operationName(run.operation)}</strong><em className={`telemetry-run-status telemetry-run-status-${run.status}`}>{statusName(run.status)}</em></span>
            <span className="telemetry-run-subtitle">{MODULE_NAMES[run.module] || run.module} · {clock(run.started_at)} · 전체 {elapsed(run.wall_duration_ms)}</span>
            <span className="telemetry-run-numbers">모델 {count(run.llm_calls)}회 · 출력 {count(run.output_tokens)}토큰 · 도구 {count(run.tool_calls)}회 · 외부 API {count(run.external_calls)}회</span>
            <span className="telemetry-run-expand">{selectedRunId === run.run_id ? "접기 ▲" : "흐름 보기 ▼"}</span>
          </button>
          <div className="telemetry-run-meta">
            <button title={run.session_id} onClick={() => chooseSession(run.session_id)}>세션 {run.session_id.slice(0, 8)}…</button>
            {run.subject_id && <span title={run.subject_id}>익명 사용자 {run.subject_id.slice(0, 8)}…</span>}
            <span title={run.run_id}>작업 ID {run.run_id.slice(0, 8)}…</span>
          </div>
          {selectedRunId === run.run_id && (detailLoading ? <div className="loading-bar">작업 흐름을 불러오는 중…</div> : detail && <RunDetail detail={detail} />)}
        </article>
      ))}
      <div className="telemetry-pagination">
        <span>{activity?.total ? `${count(offset + 1)}–${count(Math.min(offset + pageSize, activity.total))}` : "0"} / {count(activity?.total)}건</span>
        <div>
          <button className="btn btn-sm" disabled={loading || offset === 0} onClick={() => { setOffset(Math.max(0, offset - pageSize)); setSelectedRunId(""); }}>이전</button>
          <button className="btn btn-sm" disabled={loading || !activity || offset + pageSize >= activity.total} onClick={() => { setOffset(offset + pageSize); setSelectedRunId(""); }}>다음</button>
        </div>
      </div>
    </section>
  );
}
