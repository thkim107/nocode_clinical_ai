// Vite `base`(빌드 인자 BASE_PATH)를 따라가는 API prefix.
// "/" 빌드면 "/api", "/apps/research-agent/" 빌드면 "/apps/research-agent/api".
export const API_BASE = `${import.meta.env.BASE_URL.replace(/\/$/, "")}/api`;

const SESSION_KEY = "platform.telemetrySessionId";

export function createRunId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export function getTelemetrySessionId(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    const created = createRunId();
    sessionStorage.setItem(SESSION_KEY, created);
    return created;
  } catch {
    return createRunId();
  }
}

export function withTelemetryHeaders(headers?: HeadersInit, runId?: string): Headers {
  const merged = new Headers(headers);
  merged.set("X-Session-ID", getTelemetrySessionId());
  merged.set("X-Run-ID", runId || createRunId());
  try {
    const userCode = localStorage.getItem("platform.userCode");
    if (userCode) merged.set("X-User-Code", userCode);
  } catch {}
  return merged;
}
