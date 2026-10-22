import type { LsResponse, PreviewData } from "../types";
import { API_BASE, withTelemetryHeaders } from "./base";

const BASE = API_BASE;

/**
 * fetch with automatic retry on network errors (e.g. after idle periods).
 * Only retries on TypeError (network failure), not on HTTP error responses.
 */
export async function fetchWithRetry(
  input: RequestInfo,
  init?: RequestInit,
  maxRetries = 2,
): Promise<Response> {
  const requestInit = { ...init, headers: withTelemetryHeaders(init?.headers) };
  for (let attempt = 0; ; attempt++) {
    try {
      const res = await fetch(input, requestInit);
      return res;
    } catch (err) {
      if (attempt >= maxRetries || !(err instanceof TypeError)) throw err;
      // brief pause before retry
      await new Promise((r) => setTimeout(r, 500 * (attempt + 1)));
    }
  }
}

export async function fetchLs(path: string): Promise<LsResponse> {
  const res = await fetch(`${BASE}/ls?path=${encodeURIComponent(path)}`, { headers: withTelemetryHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchPreview(path: string): Promise<PreviewData | { blobUrl: string; mediaType: string; modified: string }> {
  const res = await fetch(`${BASE}/preview?path=${encodeURIComponent(path)}`, {
    cache: "no-store",
    headers: withTelemetryHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());

  const ct = res.headers.get("content-type") || "";
  if (ct.startsWith("image/")) {
    const blob = await res.blob();
    return {
      blobUrl: URL.createObjectURL(blob),
      mediaType: ct,
      modified: res.headers.get("X-File-Modified") || "",
    };
  }
  return res.json();
}

export function getDownloadUrl(path: string): string {
  return `${BASE}/download?path=${encodeURIComponent(path)}`;
}

export async function uploadFiles(path: string, files: File[]): Promise<void> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch(`${BASE}/upload?path=${encodeURIComponent(path)}`, {
    method: "POST",
    headers: withTelemetryHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function createDir(path: string): Promise<void> {
  const res = await fetch(`${BASE}/mkdir?path=${encodeURIComponent(path)}`, {
    method: "POST",
    headers: withTelemetryHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}

export async function deleteItem(path: string): Promise<void> {
  const res = await fetch(`${BASE}/delete?path=${encodeURIComponent(path)}`, {
    method: "DELETE",
    headers: withTelemetryHeaders(),
  });
  if (!res.ok) throw new Error(await res.text());
}
