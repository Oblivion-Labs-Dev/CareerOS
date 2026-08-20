"use client";

import React, { useState } from "react";
import {
  IconActivity,
  IconAlertCircle,
  IconArrowRight,
  IconCheckCircle,
  IconClock,
  IconSend,
  IconShieldCheck,
} from "./icons";

interface ActivityLogItem {
  id: string;
  timestamp: string;
  level: "info" | "warning" | "error";
  message: string;
  metadata?: any;
}

interface RecentActivityPanelProps {
  logs: ActivityLogItem[];
}

function parseActivityItem(log: ActivityLogItem) {
  const msg = log.message;
  let icon = IconActivity;
  let color = "text-[#2ee8c9]";
  let title = "Autopilot Activity";
  let detail = msg;

  if (msg.includes("Successfully submitted") || msg.includes("Application confirmed")) {
    icon = IconSend;
    color = "text-[#2ee8c9]";
    title = "Application Submitted";
  } else if (msg.includes("Staged application") || msg.includes("Ambiguous question")) {
    icon = IconClock;
    color = "text-amber-400";
    title = "Staged for Review";
  } else if (msg.includes("Pre-submit") || msg.includes("safety check")) {
    icon = IconShieldCheck;
    color = "text-[#38bdf8]";
    title = "Pre-Submission Safety Check";
  } else if (msg.includes("error") || log.level === "error") {
    icon = IconAlertCircle;
    color = "text-rose-400";
    title = "Automation Event";
  } else if (msg.includes("Ranked") || msg.includes("eligible")) {
    icon = IconCheckCircle;
    color = "text-emerald-400";
    title = "Job Matching & Ranking";
  }

  if (msg.includes("Processing job:") || msg.includes("Application submitted:") || msg.includes("Staged application")) {
    const parts = msg.split(/[:—]/);
    if (parts.length >= 2) {
      detail = parts.slice(1).join(" — ").trim();
    }
  }

  return { icon, color, title, detail };
}

export function RecentActivityPanel({ logs }: RecentActivityPanelProps) {
  const [showFullModal, setShowFullModal] = useState(false);
  const [copied, setCopied] = useState(false);

  const displayLogs = logs.slice(-8).reverse();

  const handleCopyLogs = async () => {
    const formatted = logs
      .map((l) => `[${new Date(l.timestamp).toISOString()}] [${l.level.toUpperCase()}] ${l.message}`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(formatted);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <div className="p-5 rounded-2xl border border-white/10 bg-gradient-to-b from-[#0c121c] to-[#070b12] shadow-xl backdrop-blur-xl space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <IconActivity className="w-4 h-4 text-[#2ee8c9]" />
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-200">Recent Activity</h3>
        </div>

        <div className="flex items-center gap-2">
          {logs.length > 0 && (
            <button
              onClick={handleCopyLogs}
              className="px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-[11px] font-semibold text-slate-300 hover:text-white flex items-center gap-1.5 transition-all cursor-pointer"
              title="Copy all logs to clipboard"
            >
              <span>{copied ? "✓ Copied" : "📋 Copy Logs"}</span>
            </button>
          )}

          <button
            onClick={() => setShowFullModal(true)}
            className="text-xs font-semibold text-slate-400 hover:text-[#2ee8c9] flex items-center gap-1 transition-colors cursor-pointer"
          >
            View Full Log <IconArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Grid of timeline cards */}
      {displayLogs.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          {displayLogs.map((log) => {
            const { icon: EventIcon, color, title, detail } = parseActivityItem(log);
            const timeStr = new Date(log.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

            return (
              <div
                key={log.id}
                className="p-3 rounded-xl bg-[#060a10] border border-white/5 hover:border-white/10 transition-all flex items-start gap-3"
              >
                <div className="shrink-0 pt-0.5">
                  <span className="text-[11px] font-mono text-slate-500 block w-14">
                    {timeStr}
                  </span>
                </div>

                <div className={`p-1.5 rounded-lg bg-white/5 ${color} shrink-0`}>
                  <EventIcon className="w-3.5 h-3.5" />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="text-xs font-bold text-slate-200 truncate">{title}</div>
                  <div className="text-[11px] text-slate-400 mt-0.5 line-clamp-2 leading-relaxed">
                    {detail}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="p-6 rounded-xl bg-[#060a10] border border-white/5 text-center text-xs text-slate-500 italic">
          No activity events logged in this session yet.
        </div>
      )}

      {/* Full Log Modal / Drawer */}
      {showFullModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
          <div className="w-full max-w-3xl rounded-2xl border border-white/15 bg-[#090e17] p-6 shadow-2xl space-y-4 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <IconActivity className="w-4 h-4 text-[#2ee8c9]" />
                <h3 className="text-sm font-bold text-white">Full Autopilot Event Log</h3>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopyLogs}
                  className="px-3 py-1.5 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-bold text-slate-200 hover:text-white flex items-center gap-1.5 transition-all cursor-pointer"
                >
                  <span>{copied ? "✓ Copied" : "📋 Copy All"}</span>
                </button>
                <button
                  onClick={() => setShowFullModal(false)}
                  className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white flex items-center justify-center cursor-pointer"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto space-y-2 font-mono text-xs pr-2">
              {logs.slice().reverse().map((log) => (
                <div key={log.id} className="p-2.5 rounded-xl bg-[#05080f] border border-white/5 flex items-start gap-3">
                  <span className="text-slate-500 shrink-0">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </span>
                  <span className={log.level === "error" ? "text-rose-400 font-semibold" : log.level === "warning" ? "text-amber-400" : "text-slate-300"}>
                    {log.message}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
