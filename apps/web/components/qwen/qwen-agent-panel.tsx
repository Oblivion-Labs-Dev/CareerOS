"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

interface QwenMetrics {
  totalRequests: number;
  successCount: number;
  errorCount: number;
  chatCount: number;
  completionCount: number;
  avgLatencyMs: number;
  errorRate: number;
  lastRequestAt: string | null;
  lastError: string | null;
  model: string;
  provider: string;
  connected: boolean;
  lastCheckedAt: string | null;
}

interface QwenLog {
  id: string;
  timestamp: string;
  type: string;
  model: string;
  success: boolean;
  latencyMs: number;
  summary: string;
  error: string;
}

interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  id?: string;
}

interface TrackerContext {
  applicationsCount?: number;
  submittedCount?: number;
  interviewingCount?: number;
  applicationId?: string;
}

interface QwenAgentPanelProps {
  trackerContext?: TrackerContext;
}

function formatTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

const QUICK_PROMPTS = [
  "What went wrong with the last application prep?",
  "What UI or backend fix do you recommend?",
  "Summarize your latest activity log entries.",
];

function LatencySparkline({ values }: { values: number[] }) {
  if (!values.length) return <p className="muted aa-spark-empty">No latency data yet</p>;
  const max = Math.max(...values, 1);
  const width = 120;
  const height = 36;
  const points = values
    .slice(0, 12)
    .reverse()
    .map((v, i, arr) => {
      const x = (i / Math.max(arr.length - 1, 1)) * width;
      const y = height - (v / max) * (height - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="aa-sparkline" viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline fill="none" stroke="currentColor" strokeWidth="2" points={points} />
    </svg>
  );
}

export function QwenAgentPanel({ trackerContext }: QwenAgentPanelProps) {
  const [metrics, setMetrics] = useState<QwenMetrics | null>(null);
  const [logs, setLogs] = useState<QwenLog[]>([]);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [showLogs, setShowLogs] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "I'm Qwen — I run application prep autonomously and log every step. Watch the activity log, or ask me what went wrong and I'll suggest UI/backend fixes.",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [livePrep, setLivePrep] = useState(false);
  const [activeAppId, setActiveAppId] = useState<string | undefined>(trackerContext?.applicationId);
  const [activeJobLabel, setActiveJobLabel] = useState("");
  const [agentRun, setAgentRun] = useState<Record<string, unknown> | null>(null);
  const [analyzeActive, setAnalyzeActive] = useState(false);

  const chatMessagesRef = useRef<HTMLDivElement>(null);
  const logsListRef = useRef<HTMLDivElement>(null);
  const seenLogIds = useRef<Set<string>>(new Set());
  const initializedLogs = useRef(false);

  const refresh = useCallback(async () => {
    const base = getClientApiBaseUrl();
    try {
      const [statusRes, liveRes] = await Promise.all([
        fetch(`${base}/application-assistant/qwen/status`, { cache: "no-store" }),
        fetch(`${base}/application-assistant/qwen/live`, { cache: "no-store" }),
      ]);

      if (statusRes.ok) {
        const status = await statusRes.json();
        setConnected(status.connected);
        setModel(status.model || "");
        setBaseUrl(status.baseUrl || "");
        setMetrics(status.metrics || null);
      }

      if (liveRes.ok) {
        const data = await liveRes.json();
        const newLogs: QwenLog[] = data.logs || [];
        setLogs(newLogs);
        setLivePrep(Boolean(data.activePrep?.active));
        setAgentRun(data.agentRun || null);
        if (data.activePrep?.applicationId) {
          setActiveAppId(String(data.activePrep.applicationId));
        }
        if (data.activeAnalyze?.active) {
          setAnalyzeActive(true);
        } else if (!data.activePrep?.active) {
          setAnalyzeActive(false);
        }

        if (!initializedLogs.current) {
          newLogs.forEach((l) => seenLogIds.current.add(l.id));
          initializedLogs.current = true;
        } else if (livePrep || data.activePrep?.active || data.activeAnalyze?.active) {
          const fresh = newLogs.filter(
            (l) => !seenLogIds.current.has(l.id) && (
              l.type.startsWith("agent_")
              || l.type.startsWith("prep_")
              || l.type.startsWith("analyze_")
            ),
          );
          if (fresh.length) {
            fresh.reverse().forEach((log) => {
              seenLogIds.current.add(log.id);
              setMessages((prev) => [
                ...prev,
                {
                  id: log.id,
                  role: "system",
                  content: `[${log.type}] ${log.summary}${log.error ? ` — ${log.error}` : ""}`,
                },
              ]);
            });
          }
        }
      }
    } catch {
      setConnected(false);
    }
  }, [livePrep]);

  useEffect(() => {
    if (!livePrep && !analyzeActive) return;
    void refresh();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  }, [refresh, livePrep, analyzeActive]);

  useEffect(() => {
    const onPrepStarted = () => {
      setLivePrep(true);
      void refresh();
    };
    const onAnalyzeStarted = () => {
      setAnalyzeActive(true);
      setShowLogs(true);
      void refresh();
    };
    const onAppContext = (e: Event) => {
      const detail = (e as CustomEvent).detail as { applicationId?: string; companyName?: string; roleTitle?: string };
      if (detail.applicationId) setActiveAppId(detail.applicationId);
      if (detail.companyName || detail.roleTitle) {
        setActiveJobLabel(`${detail.companyName || ""} — ${detail.roleTitle || ""}`.trim());
      }
    };
    const onChatReply = (e: Event) => {
      const detail = (e as CustomEvent).detail as { reply?: string };
      if (detail.reply) {
        setMessages((prev) => [...prev, { role: "assistant", content: detail.reply! }]);
      }
    };
    window.addEventListener("qwen-prep-started", onPrepStarted);
    window.addEventListener("qwen-analyze-started", onAnalyzeStarted);
    window.addEventListener("qwen-app-context", onAppContext);
    window.addEventListener("qwen-chat-reply", onChatReply);
    return () => {
      window.removeEventListener("qwen-prep-started", onPrepStarted);
      window.removeEventListener("qwen-analyze-started", onAnalyzeStarted);
      window.removeEventListener("qwen-app-context", onAppContext);
      window.removeEventListener("qwen-chat-reply", onChatReply);
    };
  }, [refresh]);

  useEffect(() => {
    if (livePrep && logsListRef.current) {
      logsListRef.current.scrollTop = 0;
    }
  }, [logs, livePrep]);

  useEffect(() => {
    const el = chatMessagesRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, sending]);

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    setError("");
    setSending(true);
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);

    try {
      const history = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-10)
        .map((m) => ({ role: m.role, content: m.content }));

      const res = await fetch(`${getClientApiBaseUrl()}/application-assistant/qwen/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          history,
          context: { ...trackerContext, applicationId: activeAppId },
        }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Chat request failed");

      setMessages((prev) => [...prev, { role: "assistant", content: data.reply || "" }]);
      void refresh();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to reach Qwen";
      setError(msg);
      setMessages((prev) => [...prev, { role: "assistant", content: `Sorry — I couldn't respond. ${msg}` }]);
    } finally {
      setSending(false);
    }
  }

  const agentLogs = logs.filter((l) =>
    l.type.startsWith("agent_") || l.type.startsWith("prep_") || l.type.startsWith("analyze_"),
  );
  const latencyValues = logs.filter((l) => l.latencyMs > 0).map((l) => l.latencyMs);
  const successRate = metrics && metrics.totalRequests > 0
    ? Math.round((metrics.successCount / metrics.totalRequests) * 100)
    : null;

  return (
    <section className="qwen-agent-panel" aria-label="Qwen local agent">
      <div className="qwen-agent-header">
        <div>
          <span className="toc-card-kicker">Autonomous agent</span>
          <h2>Qwen assistant</h2>
          <p className="muted">
            {livePrep
              ? `Working on ${activeJobLabel || "an application"} — live updates stream below.`
              : "Qwen runs prep, logs every step, and diagnoses failures. You watch logs or ask what to fix."}
          </p>
        </div>
        <div className="qwen-status-badge">
          {livePrep && <span className="qwen-live-badge">Live</span>}
          <span className={`qwen-dot ${connected ? "qwen-dot--online" : "qwen-dot--offline"}`} aria-hidden />
          {connected === null ? "Checking…" : connected ? "Connected" : "Offline"}
        </div>
      </div>

      {analyzeActive && !livePrep && (
        <div className="aa-live-prep-banner" role="status">
          Qwen is analyzing application questions — watch the activity log below.
        </div>
      )}

      {agentRun && livePrep && (
        <div className="aa-live-prep-banner" role="status">
          <strong>{String(agentRun.companyName || "Application")}</strong>
          {" · "}
          {String(agentRun.roleTitle || "")}
          {" · "}
          Status: {String(agentRun.status || "running")}
          {agentRun.verifiedCount != null && <> · {String(agentRun.verifiedCount)} verified</>}
        </div>
      )}

      <div className="qwen-metrics-grid" aria-label="Qwen metrics">
        <div className="qwen-metric-card">
          <span>Model</span>
          <strong>{model || "—"}</strong>
          <p>{baseUrl || "Not configured"}</p>
        </div>
        <div className="qwen-metric-card">
          <span>Agent steps</span>
          <strong>{agentLogs.length}</strong>
          <p>{metrics?.totalRequests ?? 0} total LLM calls</p>
        </div>
        <div className="qwen-metric-card">
          <span>Success rate</span>
          <strong>{successRate != null ? `${successRate}%` : "—"}</strong>
          <LatencySparkline values={latencyValues} />
        </div>
        <div className="qwen-metric-card">
          <span>Avg latency</span>
          <strong>{metrics?.avgLatencyMs ? `${Math.round(metrics.avgLatencyMs)}ms` : "—"}</strong>
          <p>Last: {formatTime(metrics?.lastRequestAt)}</p>
        </div>
      </div>

      <div className="qwen-agent-body">
        <div className="qwen-logs-panel">
          <div className="qwen-panel-toolbar">
            <h3>Activity log</h3>
            <button type="button" className="btn-secondary btn-sm" onClick={() => setShowLogs(!showLogs)}>
              {showLogs ? "Collapse" : "Expand"}
            </button>
            <button type="button" className="btn-secondary btn-sm" onClick={() => void refresh()}>
              Refresh
            </button>
          </div>
          {showLogs && (
            <div className="qwen-logs-list" ref={logsListRef}>
              {logs.length === 0 ? (
                <p className="muted">No activity yet. Click &quot;Start application&quot; on a job to begin.</p>
              ) : (
                logs.map((log) => (
                  <div key={log.id} className={`qwen-log-item ${log.success ? "" : "qwen-log-item--error"}`}>
                    <div className="qwen-log-meta">
                      <span className={`qwen-log-type qwen-log-type--${log.type}`}>{log.type}</span>
                      <time dateTime={log.timestamp}>{formatTime(log.timestamp)}</time>
                      {log.latencyMs > 0 && <span>{log.latencyMs}ms</span>}
                      {!log.success && <span className="qwen-log-fail">failed</span>}
                    </div>
                    <p className="qwen-log-summary">{log.summary || log.error || "—"}</p>
                  </div>
                ))
              )}
            </div>
          )}
          {metrics?.lastError && <p className="qwen-last-error">Last error: {metrics.lastError}</p>}
        </div>

        <div className="qwen-chat-panel">
          <h3>Conversation {livePrep && <span className="qwen-live-badge">Live</span>}</h3>
          <div className="qwen-quick-prompts">
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                className="btn-secondary btn-sm"
                disabled={sending || connected === false}
                onClick={() => void sendMessage(prompt)}
              >
                {prompt}
              </button>
            ))}
          </div>
          <div className="qwen-chat-messages" ref={chatMessagesRef} role="log" aria-live="polite">
            {messages.map((msg, i) => (
              <div
                key={msg.id || i}
                className={`qwen-chat-bubble qwen-chat-bubble--${msg.role === "system" ? "assistant qwen-chat-bubble--live" : msg.role}`}
              >
                <span className="qwen-chat-role">
                  {msg.role === "user" ? "You" : msg.role === "system" ? "Qwen (live)" : "Qwen"}
                </span>
                <p>{msg.content}</p>
              </div>
            ))}
            {sending && (
              <div className="qwen-chat-bubble qwen-chat-bubble--assistant">
                <span className="qwen-chat-role">Qwen</span>
                <p className="qwen-chat-typing">Thinking…</p>
              </div>
            )}
          </div>
          {error && <p className="qwen-chat-error" role="alert">{error}</p>}
          <form
            className="qwen-chat-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              void sendMessage(input);
            }}
          >
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={connected ? "What went wrong? What should we fix?" : "Qwen offline — start Ollama first"}
              disabled={sending || connected === false}
              aria-label="Message to Qwen"
            />
            <button type="submit" className="btn-primary" disabled={sending || !input.trim() || connected === false}>
              Send
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
