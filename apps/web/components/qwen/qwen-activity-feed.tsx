"use client";

import { useEffect, useRef, useState } from "react";
import { getQwenLogs } from "@/lib/application-assistant-api";

export type QwenActivityLog = {
  id: string;
  timestamp: string;
  type: string;
  summary: string;
  success: boolean;
  latencyMs?: number;
  error?: string;
  metadata?: Record<string, unknown>;
};

function formatLogTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
}

function isAnalyzeLog(log: QwenActivityLog, applicationId?: string) {
  if (!log.type.startsWith("analyze_")) return false;
  if (!applicationId) return true;
  const metaAppId = log.metadata?.applicationId;
  return !metaAppId || metaAppId === applicationId;
}

export function QwenActivityFeed({
  active,
  applicationId,
  title = "Qwen activity",
  maxHeight = 180,
}: {
  active: boolean;
  applicationId?: string;
  title?: string;
  maxHeight?: number;
}) {
  const [logs, setLogs] = useState<QwenActivityLog[]>([]);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active) {
      setLogs([]);
      return;
    }

    let cancelled = false;

    async function poll() {
      try {
        const res = await getQwenLogs(100);
        if (cancelled) return;
        const filtered = (res.logs as QwenActivityLog[])
          .filter((log) => isAnalyzeLog(log, applicationId))
          .reverse();
        setLogs(filtered);
      } catch {
        /* backend may be offline */
      }
    }

    void poll();
    const id = setInterval(poll, 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [active, applicationId]);

  useEffect(() => {
    if (!active || !listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [logs, active]);

  if (!active) return null;

  return (
    <div className="aa-qwen-activity-feed" role="log" aria-live="polite" aria-label={title}>
      <div className="aa-qwen-activity-feed-header">
        <strong>{title}</strong>
        <span className="qwen-live-badge">Live</span>
      </div>
      <div
        className="aa-qwen-activity-feed-list"
        ref={listRef}
        style={{ maxHeight }}
      >
        {logs.length === 0 ? (
          <p className="muted">Waiting for Qwen…</p>
        ) : (
          logs.map((log) => (
            <div
              key={log.id}
              className={`aa-qwen-activity-line${log.success ? "" : " aa-qwen-activity-line--error"}`}
            >
              <time dateTime={log.timestamp}>{formatLogTime(log.timestamp)}</time>
              <span className={`aa-qwen-activity-type aa-qwen-activity-type--${log.type.replace(/_/g, "-")}`}>
                {log.type.replace("analyze_", "")}
              </span>
              <p>{log.summary}</p>
              {log.latencyMs ? <span className="aa-qwen-activity-meta">{log.latencyMs}ms</span> : null}
              {log.error ? <span className="aa-qwen-activity-meta">{log.error}</span> : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
