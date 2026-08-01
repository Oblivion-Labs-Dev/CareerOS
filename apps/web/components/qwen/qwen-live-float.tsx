"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { getQwenLogs, type QwenActivityLog } from "@/lib/application-assistant-api";

export type LiveLogLine = {
  id: string;
  timestamp: string;
  type: string;
  summary: string;
  success: boolean;
  latencyMs?: number;
  error?: string;
  local?: boolean;
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

export function QwenLiveFloat({
  open,
  title,
  subtitle,
  applicationId,
  elapsedSec = 0,
  localLines = [],
}: {
  open: boolean;
  title: string;
  subtitle?: string;
  applicationId?: string;
  elapsedSec?: number;
  localLines?: LiveLogLine[];
}) {
  const [remoteLogs, setRemoteLogs] = useState<QwenActivityLog[]>([]);
  const [pollError, setPollError] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      setRemoteLogs([]);
      setPollError("");
      return;
    }

    let cancelled = false;

    async function poll() {
      try {
        const res = await getQwenLogs(120);
        if (cancelled) return;
        setPollError("");
        const filtered = (res.logs as QwenActivityLog[])
          .filter((log) => isAnalyzeLog(log, applicationId));
        setRemoteLogs(filtered);
      } catch (e) {
        if (!cancelled) {
          setPollError(e instanceof Error ? e.message : "Could not reach activity log");
        }
      }
    }

    void poll();
    const id = setInterval(poll, 800);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [open, applicationId]);

  const mergedLines = useMemo(() => {
    const remote: LiveLogLine[] = remoteLogs.map((log) => ({
      id: log.id,
      timestamp: log.timestamp,
      type: log.type,
      summary: log.summary,
      success: log.success,
      latencyMs: log.latencyMs,
      error: log.error,
    }));
    const byId = new Map<string, LiveLogLine>();
    for (const line of [...localLines, ...remote]) {
      byId.set(line.id, line);
    }
    return [...byId.values()].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }, [localLines, remoteLogs]);

  useEffect(() => {
    if (!open || !listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [mergedLines, open]);

  if (!open) return null;

  return (
    <div className="qwen-live-float" role="dialog" aria-label={title} aria-live="polite">
      <div className="qwen-live-float-header">
        <div>
          <span className="qwen-live-badge">Live</span>
          <strong>{title}</strong>
          {subtitle ? <p className="muted">{subtitle}</p> : null}
        </div>
        {elapsedSec > 0 ? <span className="qwen-live-float-elapsed">{elapsedSec}s</span> : null}
      </div>
      <div className="qwen-live-float-progress">
        <span className="page-loading-bar" />
      </div>
      <div className="qwen-live-float-list" ref={listRef}>
        {pollError && mergedLines.length === 0 ? (
          <p className="aa-qwen-activity-line--error">{pollError}</p>
        ) : null}
        {mergedLines.length === 0 ? (
          <p className="muted">Waiting for Qwen… (local model can take 30–90s per batch)</p>
        ) : (
          mergedLines.map((log) => (
            <div
              key={log.id}
              className={`qwen-live-float-line${log.success ? "" : " qwen-live-float-line--error"}${log.local ? " qwen-live-float-line--local" : ""}`}
            >
              <div className="qwen-live-float-line-meta">
                <time dateTime={log.timestamp}>{formatLogTime(log.timestamp)}</time>
                <span className="qwen-live-float-type">{log.type.replace("analyze_", "")}</span>
                {log.latencyMs ? <span className="muted">{log.latencyMs}ms</span> : null}
              </div>
              <p>{log.summary}</p>
              {log.error ? <p className="qwen-live-float-error">{log.error}</p> : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
