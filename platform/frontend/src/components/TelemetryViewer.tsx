import { useCallback, useEffect, useMemo, useState } from "react";
import {
  TELEMETRY_REPORTS,
  downloadTelemetryCsv,
  downloadTelemetrySummaryCsv,
  fetchTelemetryOverview,
  fetchTelemetryReport,
  getStoredTelemetryToken,
  storeTelemetryToken,
  type TelemetryOverview,
  type TelemetryReportName,
  type TelemetryReportResponse,
  type TelemetrySummaryKind,
} from "../api/telemetry";
import TelemetryActivity from "./TelemetryActivity";

const REPORT_LABELS: Record<TelemetryReportName, string> = {
  sessions: "세션",
  runs: "작업",
  llm_calls: "모델 호출",
  tool_calls: "도구 호출",
  external_calls: "외부 API",
  events: "단계 이벤트",
};

const DAY_OPTIONS = [
  { value: 1, label: "24시간" },
  { value: 7, label: "7일" },
  { value: 30, label: "30일" },
  { value: 90, label: "90일" },
  { value: 365, label: "1년" },
  { value: 0, label: "전체 기간" },
];

function number(value: number | null | undefined): string {
  return Number(value || 0).toLocaleString();
}

function duration(value: number | null | undefined): string {
  if (value == null) return "—";
  const ms = Number(value);
  if (ms < 1000) return `${ms.toLocaleString()} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms < 3_600_000) return `${(ms / 60_000).toFixed(1)} min`;
  return `${(ms / 3_600_000).toFixed(1)} h`;
}

function displayCell(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return value.toLocaleString();
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
    const parsed = new Date(text);
    if (!Number.isNaN(parsed.getTime())) return parsed.toLocaleString();
  }
  return text;
}

function statusClass(value: unknown): string {
  if (value === "succeeded") return "telemetry-status telemetry-status-success";
  if (value === "failed" || value === "cancelled" || value === "denied" || value === "limit_reached") {
    return "telemetry-status telemetry-status-failure";
  }
  if (value === "waiting_approval" || value === "requested" || value === "approved") {
    return "telemetry-status telemetry-status-waiting";
  }
  return "";
}

export default function TelemetryViewer() {
  const initialToken = getStoredTelemetryToken();
  const [token, setToken] = useState(initialToken);
  const [tokenInput, setTokenInput] = useState(initialToken);
  const [unlocked, setUnlocked] = useState(Boolean(initialToken));
  const [days, setDays] = useState(30);
  const [reportName, setReportName] = useState<TelemetryReportName>("runs");
  const [limit, setLimit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [overview, setOverview] = useState<TelemetryOverview>({});
  const [report, setReport] = useState<TelemetryReportResponse | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadingSummary, setDownloadingSummary] = useState<TelemetrySummaryKind | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [rawOpen, setRawOpen] = useState(false);

  const handleFailure = useCallback((caught: unknown) => {
    const problem = caught as Error & { status?: number };
    if (problem.status === 401) {
      storeTelemetryToken("");
      setToken("");
      setUnlocked(false);
      setError("조회 토큰이 올바르지 않거나 만료되었습니다.");
      return;
    }
    setError(problem.message || "작업 기록을 불러오지 못했습니다.");
  }, []);

  const load = useCallback(async () => {
    if (!unlocked || !token) return;
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const [overviewData, reportData] = await Promise.all([
        fetchTelemetryOverview(token, days),
        rawOpen ? fetchTelemetryReport(token, reportName, days, limit, offset) : Promise.resolve(null),
      ]);
      setOverview(overviewData);
      if (reportData) setReport(reportData);
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setLoading(false);
    }
  }, [days, handleFailure, limit, offset, rawOpen, reportName, token, unlocked]);

  useEffect(() => {
    void load();
  }, [load]);

  const unlock = () => {
    const next = tokenInput.trim();
    if (!next) return;
    storeTelemetryToken(next);
    setToken(next);
    setUnlocked(true);
    setOffset(0);
  };

  const lock = () => {
    storeTelemetryToken("");
    setToken("");
    setTokenInput("");
    setUnlocked(false);
    setOverview({});
    setReport(null);
    setError("");
  };

  const selectReport = (name: TelemetryReportName) => {
    setReportName(name);
    setOffset(0);
    setSearch("");
  };

  const rows = useMemo(() => {
    const source = report?.rows || [];
    const needle = search.trim().toLowerCase();
    if (!needle) return source;
    return source.filter((row) =>
      Object.values(row).some((value) => displayCell(value).toLowerCase().includes(needle)),
    );
  }, [report, search]);

  const exportCsv = async () => {
    if (!token) return;
    setDownloading(true);
    setError("");
    setNotice("");
    try {
      const exported = await downloadTelemetryCsv(token, reportName, days);
      const capped = exported.limit > 0 && exported.count >= exported.limit;
      setNotice(
        capped
          ? `${exported.count.toLocaleString()} rows exported (export limit reached).`
          : `${exported.count.toLocaleString()} rows exported.`,
      );
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setDownloading(false);
    }
  };

  const exportSummaryCsv = async (kind: TelemetrySummaryKind) => {
    if (!token) return;
    setDownloadingSummary(kind);
    setError("");
    setNotice("");
    try {
      const exported = await downloadTelemetrySummaryCsv(token, kind, days);
      const label = kind === "runs" ? "작업별" : "세션별";
      const capped = exported.limit > 0 && exported.count >= exported.limit;
      setNotice(`${label} 요약 ${exported.count.toLocaleString()}행을 다운로드했습니다.${capped ? " 최대 내보내기 행 수에 도달했습니다." : ""}`);
    } catch (caught) {
      handleFailure(caught);
    } finally {
      setDownloadingSummary(null);
    }
  };

  if (!unlocked) {
    return (
      <div className="panel telemetry-panel">
        <div className="telemetry-auth-card">
          <h2>작업 기록 뷰어</h2>
          <p>관리자에게 받은 조회 토큰을 입력하세요.</p>
          <div className="telemetry-auth-form">
            <input
              type="password"
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && unlock()}
              placeholder="조회 토큰"
              autoComplete="off"
            />
            <button className="btn btn-primary" onClick={unlock} disabled={!tokenInput.trim()}>
              기록 보기
            </button>
          </div>
          {error && <div className="error-banner">{error}</div>}
          <p className="text-muted">토큰은 현재 브라우저 탭에만 저장됩니다.</p>
        </div>
      </div>
    );
  }

  const runCount = Number(overview.runs || 0);
  const successCount = Number(overview.successful_runs || 0);
  const successRate = runCount ? `${((successCount / runCount) * 100).toFixed(1)}%` : "—";
  const end = report ? Math.min(report.offset + report.limit, report.total) : 0;
  const start = report && report.total ? report.offset + 1 : 0;

  return (
    <div className="panel telemetry-panel">
      <div className="telemetry-heading">
        <div>
          <h2>작업 기록</h2>
          <p className="text-muted">사용자의 실제 작업과 모델·도구 호출을 시간순으로 확인합니다. 화면 자동 조회는 기본 지표에서 제외합니다.</p>
        </div>
        <div className="telemetry-heading-actions">
          <select value={days} onChange={(event) => { setDays(Number(event.target.value)); setOffset(0); }}>
            {DAY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          <button className="btn" onClick={() => void load()} disabled={loading}>새로고침</button>
          <button className="btn" onClick={lock}>잠금</button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {notice && <div className="info-card">{notice}</div>}
      {!loading && runCount === 0 && (
        <div className="info-card">
          선택한 기간에 실제 사용자 작업은 기록되지 않았습니다. 화면 자동 조회 {number(overview.background_requests)}건은 기본 지표에서 제외했습니다.
        </div>
      )}

      <div className="telemetry-kpis">
        <div className="telemetry-kpi"><span>작업한 세션</span><strong>{number(overview.sessions)}</strong></div>
        <div className="telemetry-kpi"><span>실제 작업</span><strong>{number(overview.runs)}</strong></div>
        <div className="telemetry-kpi"><span>작업 성공률</span><strong>{successRate}</strong></div>
        <div className="telemetry-kpi"><span>생성 토큰</span><strong>{number(overview.output_tokens)}</strong></div>
        <div className="telemetry-kpi"><span>전체 토큰</span><strong>{number(overview.total_tokens)}</strong></div>
        <div className="telemetry-kpi"><span>모델 호출</span><strong>{number(overview.llm_calls)}</strong></div>
        <div className="telemetry-kpi"><span>도구 호출</span><strong>{number(overview.tool_calls)}</strong></div>
        <div className="telemetry-kpi"><span>평균 작업 시간</span><strong>{duration(overview.mean_wall_ms)}</strong></div>
        <div className="telemetry-kpi"><span>평균 승인 대기</span><strong>{duration(overview.mean_approval_wait_ms)}</strong></div>
        <div className="telemetry-kpi"><span>외부 API 호출</span><strong>{number(overview.external_calls)}</strong></div>
      </div>

      <div className="telemetry-export-bar">
        <div>
          <strong>요약 보고서 다운로드</strong>
          <span>선택한 기간의 실제 작업만 포함합니다. 엑셀에서 열 수 있는 CSV이며 최대 100,000행입니다.</span>
        </div>
        <div className="telemetry-export-actions">
          <button className="btn btn-secondary" onClick={() => void exportSummaryCsv("runs")} disabled={downloadingSummary !== null}>
            {downloadingSummary === "runs" ? "생성 중…" : "작업별 요약 CSV"}
          </button>
          <button className="btn btn-secondary" onClick={() => void exportSummaryCsv("sessions")} disabled={downloadingSummary !== null}>
            {downloadingSummary === "sessions" ? "생성 중…" : "세션별 요약 CSV"}
          </button>
        </div>
      </div>

      <TelemetryActivity token={token} days={days} onFailure={handleFailure} />

      <div className="telemetry-raw-intro">
        <button className="btn" onClick={() => setRawOpen((value) => !value)} aria-expanded={rawOpen}>
          {rawOpen ? "원본 로그와 CSV 접기 ▲" : "원본 로그와 CSV 보기 ▼"}
        </button>
        <span>분석용 전체 컬럼입니다. 자동 조회 {number(overview.background_requests)}건도 원본 로그에 포함됩니다.</span>
      </div>

      {rawOpen && <div className="telemetry-report-card">
        <div className="telemetry-report-tabs">
          {TELEMETRY_REPORTS.map((name) => (
            <button
              key={name}
              className={`telemetry-report-tab ${reportName === name ? "active" : ""}`}
              onClick={() => selectReport(name)}
            >
              {REPORT_LABELS[name]}
            </button>
          ))}
        </div>

        <div className="telemetry-toolbar">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          placeholder="현재 페이지에서 찾기"
          />
          <label>
            표시 행 수
            <select value={limit} onChange={(event) => { setLimit(Number(event.target.value)); setOffset(0); }}>
              {[50, 100, 250, 500].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <button className="btn btn-secondary" onClick={() => void exportCsv()} disabled={downloading}>
            {downloading ? "CSV 생성 중…" : `${REPORT_LABELS[reportName]} CSV 다운로드`}
          </button>
        </div>

        {loading ? (
          <div className="loading-bar">원본 로그를 불러오는 중…</div>
        ) : (
          <div className="telemetry-table-wrapper">
            <table className="data-table telemetry-table">
              <thead>
                <tr>{(report?.columns || []).map((column) => <th key={column}>{column}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => (
                  <tr key={`${reportName}-${report?.offset || 0}-${rowIndex}`}>
                    {(report?.columns || []).map((column) => {
                      const rendered = displayCell(row[column]);
                      return (
                        <td key={column} title={rendered} className={column === "status" ? statusClass(row[column]) : ""}>
                          {rendered}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                {!rows.length && (
                  <tr><td colSpan={Math.max(report?.columns.length || 1, 1)} className="empty-row">표시할 기록이 없습니다.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        <div className="telemetry-pagination">
          <span>{start.toLocaleString()}–{end.toLocaleString()} of {(report?.total || 0).toLocaleString()}</span>
          <div>
            <button className="btn btn-sm" disabled={!report || report.offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - limit))}>이전</button>
            <button className="btn btn-sm" disabled={!report || end >= report.total || loading} onClick={() => setOffset(offset + limit)}>다음</button>
          </div>
        </div>
      </div>}
    </div>
  );
}
