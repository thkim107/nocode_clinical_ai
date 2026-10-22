import { API_BASE, withTelemetryHeaders } from "./base";
export interface ChatStreamEvent {
  type: "text" | "tool_call" | "tool_auto_executed" | "tool_executing" | "tool_result" | "tool_calls_pending" | "error" | "done";
  content?: string;
  name?: string;
  input?: unknown;
  result?: string;
  calls?: PendingToolCall[];
  assistant_content?: unknown[];
  auto_results?: unknown[];
  conversation?: unknown[];
}

export interface PendingToolCall {
  tool_use_id: string;
  name: string;
  server: string;
  input: Record<string, unknown>;
}

export interface McpToolInfo {
  server: string;
  name: string;
  description: string;
  error?: string;
}

export async function* streamChat(
  messages: { role: string; content: unknown }[],
  options?: {
    system?: string;
    enabledServers?: string[];
    enabledTools?: string[];
    autoApproveServers?: string[];
    signal?: AbortSignal;
    runId?: string;
  }
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${API_BASE}/chat/completions`, {
    method: "POST",
    headers: withTelemetryHeaders({ "Content-Type": "application/json" }, options?.runId),
    body: JSON.stringify({
      messages,
      system: options?.system,
      enabled_servers: options?.enabledServers,
      enabled_tools: options?.enabledTools,
      auto_approve_servers: options?.autoApproveServers,
    }),
    signal: options?.signal,
  });

  if (!res.ok) {
    yield { type: "error", content: await res.text() };
    return;
  }

  yield* parseSSE(res);
}

export async function* approveTools(
  conversationMessages: unknown[],
  approvedTools: { tool_use_id: string; name: string; input: Record<string, unknown> }[],
  options?: {
    system?: string;
    enabledServers?: string[];
    enabledTools?: string[];
    autoApproveServers?: string[];
    signal?: AbortSignal;
    runId?: string;
  }
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${API_BASE}/chat/approve-tools`, {
    method: "POST",
    headers: withTelemetryHeaders({ "Content-Type": "application/json" }, options?.runId),
    body: JSON.stringify({
      messages: conversationMessages,
      approved_tools: approvedTools,
      system: options?.system,
      enabled_servers: options?.enabledServers,
      enabled_tools: options?.enabledTools,
      auto_approve_servers: options?.autoApproveServers,
    }),
    signal: options?.signal,
  });

  if (!res.ok) {
    yield { type: "error", content: await res.text() };
    return;
  }

  yield* parseSSE(res);
}

export async function denyTools(toolUseIds: string[], runId: string): Promise<void> {
  await fetch(`${API_BASE}/chat/deny-tools`, {
    method: "POST",
    headers: withTelemetryHeaders({ "Content-Type": "application/json" }, runId),
    body: JSON.stringify({ tool_use_ids: toolUseIds }),
    keepalive: true,
  });
}

async function* parseSSE(res: Response): AsyncGenerator<ChatStreamEvent> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {}
      }
    }
  }
  // Flush remaining buffer after stream ends
  if (buffer.startsWith("data: ")) {
    try {
      yield JSON.parse(buffer.slice(6));
    } catch {}
  }
}

export async function listTools(): Promise<{ tools: McpToolInfo[] }> {
  const { fetchWithRetry } = await import("./client");
  const res = await fetchWithRetry(`${API_BASE}/chat/tools`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
