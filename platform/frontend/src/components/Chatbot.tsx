import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { streamChat, approveTools, denyTools, listTools, type McpToolInfo, type PendingToolCall, type ChatStreamEvent } from "../api/chat";
import { createRunId } from "../api/base";
import type { ChatMessage } from "../types";

let msgIdCounter = 0;
const newId = () => `msg-${++msgIdCounter}`;

const SERVER_LABELS: Record<string, string> = {
  "db-connector": "DB Connector",
  "file-system": "File System",
  "ml-system": "ML System",
  "docx-system": "Docx System",
};

interface PendingApproval {
  calls: PendingToolCall[];
  assistantContent: unknown[];
  autoResults: unknown[];
}

export default function Chatbot() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Tool selection (committed = actually used, draft = editing in panel)
  const [allTools, setAllTools] = useState<McpToolInfo[]>([]);
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set());
  const [showToolPanel, setShowToolPanel] = useState(false);
  const [loadingTools, setLoadingTools] = useState(false);

  // Draft state for tool panel (applied on "적용하기")
  const [draftEnabledTools, setDraftEnabledTools] = useState<Set<string>>(new Set());
  const [draftAutoApproveServers, setDraftAutoApproveServers] = useState<Set<string>>(new Set());

  // Auto-approve per server
  const [autoApproveServers, setAutoApproveServers] = useState<Set<string>>(new Set());

  // Custom system prompt (rebuilt on apply)
  const [systemPrompt, setSystemPrompt] = useState<string | undefined>(undefined);

  // Pending tool approval
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);

  // Full conversation for API continuations
  const conversationRef = useRef<{ role: string; content: unknown }[]>([]);
  const activeRunIdRef = useRef<string | null>(null);

  // Abort controller for stopping streams
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, pendingApproval]);

  useEffect(() => { loadAvailableTools(); }, []);

  const loadAvailableTools = async () => {
    setLoadingTools(true);
    try {
      const data = await listTools();
      setAllTools(data.tools.filter((t) => !t.error));
    } catch {}
    finally { setLoadingTools(false); }
  };

  const toolsByServer = allTools.reduce<Record<string, McpToolInfo[]>>((acc, t) => {
    if (!acc[t.server]) acc[t.server] = [];
    acc[t.server].push(t);
    return acc;
  }, {});

  const openToolPanel = () => {
    setDraftEnabledTools(new Set(enabledTools));
    setDraftAutoApproveServers(new Set(autoApproveServers));
    setShowToolPanel(true);
  };

  const buildSystemPrompt = (tools: Set<string>) => {
    const servers = [...new Set([...tools].map((k) => k.split("__")[0]))];
    if (servers.length === 0) return undefined;
    const serverDescriptions: Record<string, string> = {
      "db-connector": "Query clinical databases (synthea, cdm, kmimic, mimiciv, inspire). Always specify the database name.",
      "file-system": "Read, write, and search files under /app/data.",
      "ml-system": "Run ML analysis pipelines — EDA, feature selection, model training & evaluation.",
      "docx-system": "Create and edit Word documents (research reports, IRB protocols, TRIPOD+AI reports).",
    };
    const lines = servers.map((s) => `- **${s}**: ${serverDescriptions[s] || s}`);
    return [
      "You are a clinical research scientist — not merely an assistant, but an independent researcher who drives studies forward.",
      "",
      "## Your identity",
      "- You design research, form hypotheses, choose methodologies, and execute analyses with the autonomy of a lead investigator.",
      "- When a user presents a research topic, you proactively propose study designs, identify relevant variables, suggest statistical approaches, and anticipate potential pitfalls — rather than waiting for step-by-step instructions.",
      "- You think critically: question assumptions, flag confounders, and recommend sensitivity analyses.",
      "",
      "## Your capabilities (currently enabled)",
      ...lines,
      "",
      "## How you work",
      "1. **Take initiative**: When given a research question, outline the full approach (data source → cohort selection → variables → analysis plan → expected outputs) before asking for confirmation.",
      "2. **Be thorough**: Run exploratory queries to understand the data before jumping to analysis. Check distributions, missing values, and sample sizes.",
      "3. **Document everything**: Save intermediate results as CSV files, produce well-structured Word reports, and keep a clear audit trail.",
      "4. **Communicate like a researcher**: Use precise terminology, cite statistical rationale, and present results with context (confidence intervals, effect sizes, limitations).",
      "5. **Chain tools effectively**: Combine database queries, file operations, ML pipelines, and document generation in a single workflow when appropriate.",
      "",
      "Present all results clearly with proper formatting.",
    ].join("\n");
  };

  const applyToolSelection = () => {
    const newTools = new Set(draftEnabledTools);
    const newAuto = new Set(draftAutoApproveServers);
    setEnabledTools(newTools);
    setAutoApproveServers(newAuto);
    setSystemPrompt(buildSystemPrompt(newTools));
    setPendingApproval(null);
    setShowToolPanel(false);

    // Notify in chat (only if conversation exists)
    if (messages.length > 0) {
      const serverNames = [...new Set([...newTools].map((k) => k.split("__")[0]))]
        .map((s) => SERVER_LABELS[s] || s);
      const label = serverNames.length > 0 ? serverNames.join(", ") : "없음";
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "assistant", content: `도구 설정이 변경되었습니다. 활성 서버: **${label}** (${newTools.size}개 도구)` },
      ]);
    }
  };

  const toggleTool = (key: string) => {
    setDraftEnabledTools((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  };

  const toggleServer = (server: string) => {
    const keys = (toolsByServer[server] || []).map((t) => `${t.server}__${t.name}`);
    const allOn = keys.every((k) => draftEnabledTools.has(k));
    setDraftEnabledTools((prev) => { const n = new Set(prev); keys.forEach((k) => allOn ? n.delete(k) : n.add(k)); return n; });
  };

  const toggleAutoApprove = (server: string) => {
    setDraftAutoApproveServers((prev) => {
      const n = new Set(prev);
      n.has(server) ? n.delete(server) : n.add(server);
      return n;
    });
  };

  const getOptions = useCallback(() => {
    const servers = [...new Set([...enabledTools].map((k) => k.split("__")[0]))];
    return {
      system: systemPrompt,
      enabledServers: servers.length > 0 ? servers : undefined,
      enabledTools: enabledTools.size > 0 ? [...enabledTools] : undefined,
      autoApproveServers: autoApproveServers.size > 0 ? [...autoApproveServers] : undefined,
    };
  }, [enabledTools, autoApproveServers, systemPrompt]);

  // Helper: finalize a streaming assistant message (set isStreaming=false)
  const finalizeAssistant = (id: string) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, isStreaming: false } : m)));
  };

  const processStream = async (stream: AsyncGenerator<ChatStreamEvent>) => {
    let assistantText = "";
    let assistantId = newId();
    let hadToolEvents = false;
    let hadTextAfterTools = false;
    let receivedDone = false;

    for await (const event of stream) {
      switch (event.type) {
        case "text":
          // If tools ran since last text, start a new assistant message
          if (hadToolEvents) {
            hadTextAfterTools = true;
            assistantText = "";
            assistantId = newId();
            hadToolEvents = false;
          }
          assistantText += event.content || "";
          setMessages((prev) => {
            const existing = prev.find((m) => m.id === assistantId);
            if (existing) return prev.map((m) => (m.id === assistantId ? { ...m, content: assistantText } : m));
            return [...prev, { id: assistantId, role: "assistant", content: assistantText, isStreaming: true }];
          });
          break;

        case "tool_auto_executed":
        case "tool_executing":
          // Finalize current assistant text before showing tool
          if (!hadToolEvents) finalizeAssistant(assistantId);
          hadToolEvents = true;
          setMessages((prev) => [
            ...prev,
            { id: newId(), role: "tool", content: "", toolName: event.name, toolInput: event.input, toolLoading: true },
          ]);
          break;

        case "tool_result":
          if (!hadToolEvents) finalizeAssistant(assistantId);
          hadToolEvents = true;
          // Update the last tool message with matching name
          setMessages((prev) => {
            const idx = [...prev].reverse().findIndex((m) => m.role === "tool" && m.toolName === event.name && m.toolLoading);
            if (idx !== -1) {
              const realIdx = prev.length - 1 - idx;
              return prev.map((m, i) => i === realIdx ? { ...m, toolResult: event.result, toolLoading: false } : m);
            }
            // Fallback: create new message if no matching loading message
            return [...prev, { id: newId(), role: "tool", content: "", toolName: event.name, toolResult: event.result }];
          });
          break;

        case "tool_calls_pending":
          finalizeAssistant(assistantId);
          setPendingApproval({
            calls: event.calls || [],
            assistantContent: event.assistant_content || [],
            autoResults: event.auto_results || [],
          });
          // Use the exact conversation state from backend
          if (event.conversation) {
            conversationRef.current = event.conversation as { role: string; content: unknown }[];
          }
          return;

        case "error":
          receivedDone = true;
          setMessages((prev) => [...prev, { id: newId(), role: "assistant", content: `Error: ${event.content}` }]);
          break;

        case "done":
          receivedDone = true;
          finalizeAssistant(assistantId);
          // Save full conversation state from backend for next request
          if (event.conversation) {
            conversationRef.current = event.conversation as { role: string; content: unknown }[];
          }
          break;
      }
    }

    // Stream ended — check if tools ran but no text response followed
    if (hadToolEvents && !hadTextAfterTools) {
      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: "assistant",
          content: receivedDone
            ? "도구 실행 결과를 바탕으로 응답을 생성하지 못했습니다. 다시 시도해 주세요."
            : "도구 실행 후 서버와의 연결이 끊어졌습니다. 네트워크 또는 서버 오류일 수 있습니다. 다시 시도해 주세요.",
        },
      ]);
    }
    // Finalize any lingering loading tool messages
    setMessages((prev) => prev.map((m) => m.toolLoading ? { ...m, toolLoading: false } : m));
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    activeRunIdRef.current = createRunId();

    const userMsg: ChatMessage = { id: newId(), role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setStreaming(true);
    setPendingApproval(null);

    // Use backend conversation state + new user message
    const history = [
      ...conversationRef.current,
      { role: "user", content: text },
    ];

    const abort = new AbortController();
    abortRef.current = abort;

    try {
      await processStream(streamChat(history, { ...getOptions(), signal: abort.signal, runId: activeRunIdRef.current || undefined }));
    } catch (e: any) {
      if (e.name !== "AbortError") {
        setMessages((prev) => [...prev, { id: newId(), role: "assistant", content: `Error: ${e.message}` }]);
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
    }
  };

  const handleApprove = async (approvedCalls: PendingToolCall[], optionsOverride?: ReturnType<typeof getOptions>) => {
    if (!pendingApproval) return;
    setStreaming(true);

    // Show approved tools in chat
    for (const call of approvedCalls) {
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "tool", content: "", toolName: call.name, toolInput: call.input, toolLoading: true },
      ]);
    }

    const approved = approvedCalls.map((c) => ({
      tool_use_id: c.tool_use_id,
      name: c.name,
      input: c.input,
    }));

    setPendingApproval(null);

    const abort = new AbortController();
    abortRef.current = abort;
    const opts = optionsOverride || getOptions();

    try {
      await processStream(approveTools(conversationRef.current, approved, { ...opts, signal: abort.signal, runId: activeRunIdRef.current || undefined }));
    } catch (e: any) {
      if (e.name !== "AbortError") {
        setMessages((prev) => [...prev, { id: newId(), role: "assistant", content: `Error: ${e.message}` }]);
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
    // Finalize any streaming messages
    setMessages((prev) => prev.map((m) => m.isStreaming ? { ...m, isStreaming: false } : m));
    // Finalize any loading tool messages
    setMessages((prev) => prev.map((m) => m.toolLoading ? { ...m, toolLoading: false } : m));
  };

  const handleDeny = () => {
    const denied = pendingApproval?.calls.map((call) => call.tool_use_id) || [];
    if (denied.length > 0 && activeRunIdRef.current) {
      void denyTools(denied, activeRunIdRef.current);
    }
    setPendingApproval(null);
    setMessages((prev) => [...prev, { id: newId(), role: "assistant", content: "Tool execution was denied by user." }]);
  };

  const handleAutoApproveAndRun = (server: string) => {
    const newAutoServers = new Set([...autoApproveServers, server]);
    setAutoApproveServers(newAutoServers);
    if (pendingApproval) {
      // Build options immediately with updated auto-approve (React state is async)
      const servers = [...new Set([...enabledTools].map((k) => k.split("__")[0]))];
      const opts = {
        system: systemPrompt,
        enabledServers: servers.length > 0 ? servers : undefined,
        enabledTools: enabledTools.size > 0 ? [...enabledTools] : undefined,
        autoApproveServers: [...newAutoServers],
      };
      handleApprove(pendingApproval.calls, opts);
    }
  };

  return (
    <div className="chatbot">
      <div className="chatbot-header">
        <div className="chatbot-header-top">
          <h3>MCP Chatbot</h3>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={() => {
                if (streaming) {
                  abortRef.current?.abort();
                }
                setMessages([]);
                conversationRef.current = [];
                activeRunIdRef.current = null;
                setPendingApproval(null);
                setStreaming(false);
                setInput("");
              }}
              className="btn btn-sm"
              title="New Chat"
            >
              New Chat
            </button>
            <button
              onClick={() => showToolPanel ? setShowToolPanel(false) : openToolPanel()}
              className={`btn btn-sm ${enabledTools.size > 0 ? "btn-primary" : ""}`}
            >
              Tools ({enabledTools.size}/{allTools.length})
            </button>
          </div>
        </div>
        {enabledTools.size === 0 && !showToolPanel && (
          <div className="tool-hint">Select tools to enable AI tool calling</div>
        )}
      </div>

      {/* Tool Selection Panel */}
      {showToolPanel && (
        <div className="tool-panel">
          <div className="tool-panel-header">
            <span className="tool-panel-title">Select MCP Tools</span>
            <div className="tool-panel-header-actions">
              <button onClick={loadAvailableTools} disabled={loadingTools} className="btn btn-sm btn-icon" title="Refresh">&#x21bb;</button>
              <button onClick={applyToolSelection} className="btn btn-sm btn-primary">적용하기</button>
            </div>
          </div>
          {loadingTools ? (
            <div className="tool-panel-loading">Loading tools...</div>
          ) : (<>
            <div className="tool-panel-body">
              {Object.entries(toolsByServer).map(([server, tools]) => {
                const keys = tools.map((t) => `${t.server}__${t.name}`);
                const allChecked = keys.every((k) => draftEnabledTools.has(k));
                const someChecked = keys.some((k) => draftEnabledTools.has(k));
                const isAuto = draftAutoApproveServers.has(server);
                return (
                  <div key={server} className="tool-server-group">
                    <div className="tool-server-row">
                      <label className="tool-server-label">
                        <input
                          type="checkbox"
                          checked={allChecked}
                          ref={(el) => { if (el) el.indeterminate = someChecked && !allChecked; }}
                          onChange={() => toggleServer(server)}
                        />
                        <strong>{SERVER_LABELS[server] || server}</strong>
                        <span className="text-muted">({tools.length})</span>
                      </label>
                      <button
                        onClick={() => toggleAutoApprove(server)}
                        className={`btn-auto ${isAuto ? "btn-auto-on" : ""}`}
                        title={isAuto ? "Auto-execute ON — tools run without asking" : "Click to auto-execute tools from this server"}
                      >
                        {isAuto ? "Auto" : "Manual"}
                      </button>
                    </div>
                    <div className="tool-list">
                      {tools.map((t) => {
                        const key = `${t.server}__${t.name}`;
                        return (
                          <label key={key} className="tool-item" title={t.description}>
                            <input type="checkbox" checked={draftEnabledTools.has(key)} onChange={() => toggleTool(key)} />
                            <span className="tool-name">{t.name}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </>)}
        </div>
      )}

      {/* Messages */}
      <div className="chatbot-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p>Ask me anything! I can use the tools you enable above.</p>
            <ul>
              <li><strong>DB Connector</strong> — Query clinical databases</li>
              <li><strong>File System</strong> — Read/write/search files</li>
              <li><strong>ML System</strong> — Run ML analysis pipelines</li>
              <li><strong>Docx System</strong> — Generate Word documents</li>
            </ul>
            <p className="text-muted">Tools run in <strong>Manual</strong> mode by default (requires your approval). Toggle <strong>Auto</strong> per server to skip approval.</p>
          </div>
        )}
        {messages.map((msg) => (
          msg.role === "tool" ? (
            <div key={msg.id} className="chat-msg chat-msg-tool">
              <details className="tool-box">
                <summary className="tool-box-summary">
                  <span className="tool-badge">{msg.toolName}</span>
                  {msg.toolLoading ? (
                    <span className="tool-status tool-status-loading">실행 중...</span>
                  ) : (
                    <span className="tool-status tool-status-done">완료</span>
                  )}
                </summary>
                <div className="tool-box-body">
                  {msg.toolInput != null && (
                    <div className="tool-section">
                      <div className="tool-section-label">Input</div>
                      <pre>{JSON.stringify(msg.toolInput, null, 2)}</pre>
                    </div>
                  )}
                  {msg.toolResult && (
                    <div className="tool-section">
                      <div className="tool-section-label">Result</div>
                      <pre>{msg.toolResult}</pre>
                    </div>
                  )}
                </div>
              </details>
            </div>
          ) : (
            <div key={msg.id} className={`chat-msg chat-msg-${msg.role}`}>
              <div className="chat-msg-label">
                {msg.role === "user" ? "You" : "Assistant"}
              </div>
              <div className="chat-msg-content">
                {msg.isStreaming ? (
                  <div className="markdown-body streaming-text">{msg.content}<span className="cursor" /></div>
                ) : (
                  <div className="markdown-body">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code({ className, children, ...props }) {
                          const match = /language-(\w+)/.exec(className || "");
                          const code = String(children).replace(/\n$/, "");
                          return match ? (
                            <SyntaxHighlighter style={oneDark} language={match[1]} PreTag="div">
                              {code}
                            </SyntaxHighlighter>
                          ) : (
                            <code className={className} {...props}>{children}</code>
                          );
                        },
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          )
        ))}

        {/* Pending Approval UI */}
        {pendingApproval && (
          <div className="approval-panel">
            <div className="approval-header">Tool execution requires your approval</div>
            {pendingApproval.calls.map((call) => (
              <div key={call.tool_use_id} className="approval-card">
                <div className="approval-card-header">
                  <span className="tool-badge">{call.name}</span>
                  <span className="text-muted">{SERVER_LABELS[call.server] || call.server}</span>
                </div>
                <details className="tool-details">
                  <summary>View input</summary>
                  <pre>{JSON.stringify(call.input, null, 2)}</pre>
                </details>
              </div>
            ))}
            <div className="approval-actions">
              <button onClick={() => handleApprove(pendingApproval.calls)} className="btn btn-primary">
                Approve All ({pendingApproval.calls.length})
              </button>
              <button onClick={handleDeny} className="btn btn-danger-outline">
                Deny
              </button>
              {/* Auto-approve buttons per server */}
              {[...new Set(pendingApproval.calls.map((c) => c.server))].map((server) => (
                <button
                  key={server}
                  onClick={() => handleAutoApproveAndRun(server)}
                  className="btn btn-auto-approve"
                  title={`Auto-execute all future ${SERVER_LABELS[server] || server} tools in this session`}
                >
                  Auto-run {SERVER_LABELS[server] || server}
                </button>
              ))}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="chatbot-input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
          placeholder={enabledTools.size > 0 ? "Ask a question..." : "Select tools first, or ask without tools..."}
          disabled={streaming || !!pendingApproval}
        />
        {streaming ? (
          <button onClick={handleStop} className="btn btn-danger">Stop</button>
        ) : (
          <button onClick={handleSend} disabled={!input.trim() || !!pendingApproval} className="btn btn-primary">Send</button>
        )}
      </div>
    </div>
  );
}
