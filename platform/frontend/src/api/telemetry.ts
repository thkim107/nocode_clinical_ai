import { API_BASE, withTelemetryHeaders } from "./base";

export const TELEMETRY_REPORTS = [
  "sessions",
  "runs",
  "llm_calls",
  "tool_calls",
  "external_calls",
  "events",
] as const;

export type TelemetryReportName = (typeof TELEMETRY_REPORTS)[number];
export type TelemetrySummaryKind = "runs" | "sessions";

export type TelemetryOverview = Record<string, number | null>;

export interface TelemetryReportResponse {
  report: TelemetryReportName;
  columns: string[];
  rows: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

export interface TelemetryRun {
  run_id: string;
  session_id: string;
  subject_id: string | null;
  module: string;
  operation: string;
  section: string | null;
  status: string;
  started_at: string;
  completed_at: string | null;
  wall_duration_ms: number | null;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  llm_compute_ms: number | null;
  tool_calls: number;
  manual_tool_calls: number;
  denied_tool_calls: number;
  tool_compute_ms: number | null;
  approval_wait_ms: number | null;
  external_calls: number;
  external_result_count: number | null;
}

export interface TelemetryActivityResponse {
  rows: TelemetryRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface TelemetryTimelineItem {
  id: string;
  kind: "llm" | "tool" | "external" | "event";
  at: string;
  [key: string]: unknown;
}

export interface TelemetryRunDetail {
  run: TelemetryRun;
  timeline: TelemetryTimelineItem[];
  timeline_truncated: boolean;
}

const TOKEN_KEY = "platform.telemetryViewerToken";

export function getStoredTelemetryToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function storeTelemetryToken(token: string): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {}
}

function viewerHeaders(token: string): Headers {
  const headers = withTelemetryHeaders();
  headers.set("X-Telemetry-Token", token);
  return headers;
}

async function requireOk(response: Response): Promise<Response> {
  if (response.ok) return response;
  let message = `Telemetry request failed (${response.status})`;
  try {
    const body = await response.json();
    if (body?.detail) message = String(body.detail);
  } catch {}
  const error = new Error(message) as Error & { status?: number };
  error.status = response.status;
  throw error;
}

export async function fetchTelemetryOverview(token: string, days: number): Promise<TelemetryOverview> {
  const response = await fetch(`${API_BASE}/telemetry/overview?days=${days}`, {
    headers: viewerHeaders(token),
    cache: "no-store",
  });
  return (await requireOk(response)).json();
}

export async function fetchTelemetryReport(
  token: string,
  report: TelemetryReportName,
  days: number,
  limit: number,
  offset: number,
): Promise<TelemetryReportResponse> {
  const params = new URLSearchParams({
    days: String(days),
    limit: String(limit),
    offset: String(offset),
  });
  const response = await fetch(`${API_BASE}/telemetry/reports/${report}?${params}`, {
    headers: viewerHeaders(token),
    cache: "no-store",
  });
  return (await requireOk(response)).json();
}

export async function fetchTelemetryActivity(
  token: string,
  days: number,
  limit: number,
  offset: number,
  sessionId: string,
  module: string,
): Promise<TelemetryActivityResponse> {
  const params = new URLSearchParams({
    days: String(days), limit: String(limit), offset: String(offset),
  });
  if (sessionId) params.set("session_id", sessionId);
  if (module) params.set("module", module);
  const response = await fetch(`${API_BASE}/telemetry/activity?${params}`, {
    headers: viewerHeaders(token), cache: "no-store",
  });
  return (await requireOk(response)).json();
}

export async function fetchTelemetryRunDetail(token: string, runId: string): Promise<TelemetryRunDetail> {
  const response = await fetch(`${API_BASE}/telemetry/runs/${encodeURIComponent(runId)}/detail`, {
    headers: viewerHeaders(token), cache: "no-store",
  });
  return (await requireOk(response)).json();
}

async function downloadCsv(token: string, path: string, fallbackName: string): Promise<{ count: number; limit: number }> {
  const response = await fetch(`${API_BASE}/telemetry/export/${path}`, {
    headers: viewerHeaders(token),
    cache: "no-store",
  });
  await requireOk(response);
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") || "";
  const match = /filename="([^"]+)"/.exec(disposition);
  const filename = match?.[1] || fallbackName;
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  return {
    count: Number(response.headers.get("x-exported-rows") || 0),
    limit: Number(response.headers.get("x-export-row-limit") || 0),
  };
}

export function downloadTelemetryCsv(
  token: string,
  report: TelemetryReportName,
  days: number,
): Promise<{ count: number; limit: number }> {
  return downloadCsv(token, `${report}.csv?days=${days}`, `telemetry_${report}.csv`);
}

export function downloadTelemetrySummaryCsv(
  token: string,
  kind: TelemetrySummaryKind,
  days: number,
): Promise<{ count: number; limit: number }> {
  return downloadCsv(token, `summary/${kind}.csv?days=${days}`, `telemetry_summary_${kind}.csv`);
}
