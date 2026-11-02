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

interface WorkerInfo {
  workerId: string;
  slot: number;
  status: string;
  currentJob: { id: string; company: string; title: string } | null;
  currentStep: string;
  startedAt: string;
  error: string;
  jobsCompleted: number;
  jobsFailed: number;
}

interface RecentActivityPanelProps {
  logs: ActivityLogItem[];
  workers?: WorkerInfo[];
  concurrency?: number;
}

const WORKER_STATUS_COLORS: Record<string, string> = {
  idle: "bg-slate-500",
  claiming: "bg-sky-400",
  applying: "bg-blue-500 animate-pulse",
  filling: "bg-teal-400 animate-pulse",
  submitting: "bg-emerald-400 animate-pulse",
  done: "bg-emerald-500",
  error: "bg-rose-500",
};

const WORKER_STATUS_TEXT_COLORS: Record<string, string> = {
  idle: "text-slate-400",
  claiming: "text-sky-400",
  applying: "text-blue-400",
  filling: "text-teal-400",
  submitting: "text-emerald-400",
  done: "text-emerald-400",
  error: "text-rose-400",
};

function parseActivityItem(log: ActivityLogItem) {
  const rawMsg = log.message;
  let icon = IconActivity;
  let color = "text-[#2ee8c9]";
  let title = "Autopilot Event";
  let workerSlot: number | null = null;

  // Extract worker slot from message like "[Worker 2]" or metadata
  const workerMatch = rawMsg.match(/\[Worker (\d+)\]/i);
  if (workerMatch) {
    workerSlot = parseInt(workerMatch[1], 10);
  } else if (log.metadata && typeof log.metadata.slot === "number") {
    workerSlot = log.metadata.slot;
  }

  // Strip worker prefix for parsing the detail
  const msg = rawMsg.replace(/^\[Worker \d+\]\s*/i, "").trim();
  let detail = msg;

  if (msg.includes("Successfully submitted") || msg.includes("Application confirmed")) {
    icon = IconSend;
    color = "text-[#2ee8c9]";
    title = "Application Submitted";
    detail = msg.replace(/^Successfully submitted real application for /i, "").replace(/🎉.*$/, "").trim();
  } else if (msg.startsWith("Processing:") || msg.startsWith("Processing job:")) {
    icon = IconActivity;
    color = "text-[#38bdf8]";
    title = "Processing Application";
    detail = msg.replace(/^Processing( job)?:\s*/i, "").trim();
  } else if (msg.includes("Qwen Pre-Submission Review: 100% APPROVED") || msg.includes("APPROVED ✓")) {
    icon = IconShieldCheck;
    color = "text-emerald-400";
    title = "AI Review Approved";
    detail = msg;
  } else if (msg.includes("Qwen AI Form Review") || msg.includes("Qwen Pre-Submission Review")) {
    icon = IconShieldCheck;
    color = "text-[#38bdf8]";
    title = "Qwen AI Form Review";
    detail = msg;
  } else if (msg.includes("Auto-healing") || msg.includes("Self-healed") || msg.includes("Self-Healing") || msg.includes("self-healing")) {
    icon = IconShieldCheck;
    color = "text-amber-400";
    title = "Form Self-Healing";
    detail = msg;
  } else if (msg.includes("Attached resume")) {
    icon = IconCheckCircle;
    color = "text-teal-400";
    title = "Resume Attached";
    detail = msg;
  } else if (msg.includes("Filled contact info")) {
    icon = IconActivity;
    color = "text-teal-400";
    title = "Contact Info Filled";
    detail = msg;
  } else if (msg.includes("Selected") && (msg.includes("combobox") || msg.includes("dropdown") || msg.includes("options"))) {
    icon = IconActivity;
    color = "text-indigo-400";
    title = "Dropdowns Resolved";
    detail = msg;
  } else if (msg.includes("Resolving dropdowns & comboboxes")) {
    icon = IconActivity;
    color = "text-indigo-400";
    title = "Resolving Dropdowns";
    detail = msg;
  } else if (msg.includes("Clicking final Submit button") || msg.includes("Executing final submission")) {
    icon = IconSend;
    color = "text-emerald-400";
    title = "Submitting Application";
    detail = msg;
  } else if (msg.includes("Opened application page") || msg.includes("Navigating to")) {
    icon = IconActivity;
    color = "text-[#38bdf8]";
    title = "Navigating to Job";
    detail = msg;
  } else if (msg.includes("Launching Playwright") || msg.includes("Chromium session") || msg.includes("Switched to application iframe")) {
    icon = IconActivity;
    color = "text-indigo-400";
    title = "Browser Session Active";
    detail = msg;
  } else if (msg.includes("Inspecting form DOM") || msg.includes("filling fields")) {
    icon = IconActivity;
    color = "text-teal-400";
    title = "Form Autofill Active";
    detail = msg;
  } else if (msg.includes("Claimed") && msg.includes("parallel")) {
    icon = IconCheckCircle;
    color = "text-indigo-400";
    title = "Parallel Workers Dispatched";
    detail = msg;
  } else if (msg.includes("Autopilot run started") || msg.includes("Target batch:")) {
    icon = IconCheckCircle;
    color = "text-emerald-400";
    title = "Autopilot Run Started";
    detail = msg;
  } else if (msg.includes("Autopilot run stopped") || msg.includes("Batch completed")) {
    icon = IconCheckCircle;
    color = "text-slate-300";
    title = "Batch Completed";
    detail = msg;
  } else if (msg.includes("Staged application") || msg.includes("Ambiguous question") || msg.includes("staged as")) {
    icon = IconClock;
    color = "text-amber-400";
    title = "Staged for Review";
    detail = msg;
  } else if (msg.includes("Application failed") || msg.includes("error") || log.level === "error") {
    icon = IconAlertCircle;
    color = "text-rose-400";
    title = "Submission Error";
    detail = msg.replace(/^Application failed \([^)]+\):\s*/i, "").trim();
  } else if (msg.includes("Finished:")) {
    icon = IconCheckCircle;
    color = "text-emerald-400";
    title = "Worker Finished Job";
    detail = msg;
  } else if (msg.includes("Selected") && msg.includes("eligible")) {
    icon = IconCheckCircle;
    color = "text-emerald-400";
    title = "Job Matching & Queueing";
    detail = msg;
  } else if (msg.includes("Scanning discovered job postings")) {
    icon = IconActivity;
    color = "text-sky-400";
    title = "Job Discovery Scan";
    detail = msg;
  } else {
    const parts = msg.split(/[:—]/);
    if (parts.length >= 2 && parts[0].trim().length < 40) {
      title = parts[0].trim();
      detail = parts.slice(1).join(" — ").trim();
    } else {
      title = msg.length > 35 ? msg.slice(0, 32) + "…" : msg;
      detail = msg;
    }
  }

  return { icon, color, title, detail, workerSlot, rawMessage: rawMsg };
}

function WorkerTab({
  worker,
  isActive,
  onClick,
}: {
  worker: WorkerInfo;
  isActive: boolean;
  onClick: () => void;
}) {
  const dotColor = WORKER_STATUS_COLORS[worker.status] || "bg-slate-500";
  const textColor = isActive ? "text-white" : "text-slate-400";

  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer whitespace-nowrap ${
        isActive
          ? "bg-white/10 border border-white/20 text-white"
          : "bg-transparent hover:bg-white/5 border border-transparent text-slate-400 hover:text-slate-200"
      }`}
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${dotColor}`} />
      <span className={textColor}>W{worker.slot + 1}</span>
      {worker.currentJob && (
        <span className="text-[10px] text-slate-500 truncate max-w-[80px]">
          {worker.currentJob.company}
        </span>
      )}
    </button>
  );
}

function WorkerStatusCard({ worker }: { worker: WorkerInfo }) {
  const statusColor = WORKER_STATUS_TEXT_COLORS[worker.status] || "text-slate-400";
  const dotColor = WORKER_STATUS_COLORS[worker.status] || "bg-slate-500";

  return (
    <div className="p-3 rounded-xl bg-[#060a10] border border-white/5 flex items-center gap-3">
      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${dotColor}`} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-white flex items-center gap-1">
            <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono text-[10px]">
              W{worker.slot + 1}
            </span>
            Worker {worker.slot + 1}
          </span>
          <span className={`text-[10px] font-semibold uppercase tracking-wider ${statusColor}`}>
            {worker.status}
          </span>
        </div>
        {worker.currentJob ? (
          <div className="mt-1 space-y-0.5">
            <div className="text-[11px] font-medium text-slate-300 truncate">
              {worker.currentJob.company} — {worker.currentJob.title}
            </div>
            {worker.currentStep && (
              <div className="text-[10px] font-mono text-[#38bdf8] truncate flex items-center gap-1">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#38bdf8] animate-pulse" />
                {worker.currentStep}
              </div>
            )}
          </div>
        ) : (
          <div className="text-[11px] text-slate-500 italic mt-0.5">Waiting for next job…</div>
        )}
      </div>
      <div className="flex items-center gap-3 text-[10px] text-slate-500 shrink-0">
        <span title="Completed" className="text-emerald-400 font-medium">✓ {worker.jobsCompleted}</span>
        {worker.jobsFailed > 0 && (
          <span className="text-rose-400 font-medium" title="Failed">✗ {worker.jobsFailed}</span>
        )}
      </div>
    </div>
  );
}

export function RecentActivityPanel({ logs, workers, concurrency }: RecentActivityPanelProps) {
  const [showFullModal, setShowFullModal] = useState(false);
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<number | "all">("all");

  // Keep the activity area focused on live work. Idle worker slots are already
  // represented in the metric strip and made this panel look noisier than it is.
  const visibleWorkers = (workers || []).filter(
    (worker) => (worker.status !== "idle" && worker.status !== "done") || Boolean(worker.error),
  );
  const hasWorkers = visibleWorkers.length > 0;

  // Filter logs by worker slot if a specific tab is selected
  const filteredLogs =
    activeTab === "all"
      ? logs
      : logs.filter((log) => {
          const match = log.message.match(/\[Worker (\d+)\]/i);
          const slot = match ? parseInt(match[1], 10) : log.metadata?.slot;
          return slot === activeTab;
        });

  // Keep a scrollable window of recent history rather than growing the page:
  // the panel is a fixed-height scroll area below, so showing more entries adds
  // scrollback instead of stretching the dashboard.
  const displayLogs = filteredLogs.slice(-60).reverse();

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
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-200">
            {hasWorkers ? "Worker Activity" : "Recent Activity"}
          </h3>
          {hasWorkers && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-slate-400 font-mono">
              {visibleWorkers.length}/{concurrency || workers?.length} active
            </span>
          )}
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

      {/* Worker Status Cards (when workers are active) */}
      {hasWorkers && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
          {visibleWorkers.map((w) => (
            <WorkerStatusCard key={w.workerId} worker={w} />
          ))}
        </div>
      )}

      {/* Worker Tabs */}
      {hasWorkers && (
        <div className="flex items-center gap-1 overflow-x-auto pb-1 scrollbar-thin">
          <button
            onClick={() => setActiveTab("all")}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer whitespace-nowrap ${
              activeTab === "all"
                ? "bg-white/10 border border-white/20 text-white"
                : "bg-transparent hover:bg-white/5 border border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <IconActivity className="w-3 h-3" />
            All Workers
          </button>
          {visibleWorkers.map((w) => (
            <WorkerTab
              key={w.workerId}
              worker={w}
              isActive={activeTab === w.slot}
              onClick={() => setActiveTab(w.slot)}
            />
          ))}
        </div>
      )}

      {/* Grid of timeline cards */}
      {displayLogs.length > 0 ? (
        <div className="max-h-[22rem] overflow-y-auto overscroll-contain pr-1 scrollbar-thin">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          {displayLogs.map((log) => {
            const { icon: EventIcon, color, title, detail, workerSlot } = parseActivityItem(log);
            const timeStr = new Date(log.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

            return (
              <div
                key={log.id}
                className="p-3 rounded-xl bg-[#060a10] border border-white/5 hover:border-white/10 transition-all flex items-start gap-3"
              >
                <div className="shrink-0 pt-0.5">
                  <span className="text-[11px] font-mono text-slate-500 block w-16">
                    {timeStr}
                  </span>
                </div>

                <div className={`p-1.5 rounded-lg bg-white/5 ${color} shrink-0`}>
                  <EventIcon className="w-3.5 h-3.5" />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-xs font-bold text-slate-200 truncate">{title}</span>
                    {workerSlot !== null && (
                      <span className="text-[10px] px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-300 font-mono font-bold shrink-0 border border-indigo-500/30">
                        W{workerSlot + 1}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-slate-400 mt-0.5 line-clamp-2 leading-relaxed">
                    {detail}
                  </div>
                </div>
              </div>
            );
          })}
          </div>
        </div>
      ) : (
        <div className="p-6 rounded-xl bg-[#060a10] border border-white/5 text-center text-xs text-slate-500 italic">
          {activeTab !== "all"
            ? `No activity from Worker ${(activeTab as number) + 1} yet.`
            : "No activity events logged in this session yet."}
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
              {logs.slice().reverse().map((log) => {
                const workerMatch = log.message.match(/\[Worker (\d+)\]/i);
                const slot = workerMatch ? parseInt(workerMatch[1], 10) : log.metadata?.slot;
                const cleanMsg = log.message.replace(/^\[Worker \d+\]\s*/i, "");

                return (
                  <div key={log.id} className="p-2.5 rounded-xl bg-[#05080f] border border-white/5 flex items-start gap-3">
                    <span className="text-slate-500 shrink-0">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                    {slot !== undefined && slot !== null && (
                      <span className="text-[10px] px-1.5 py-0.2 rounded bg-indigo-500/20 text-indigo-300 font-mono font-bold shrink-0 border border-indigo-500/30">
                        W{slot + 1}
                      </span>
                    )}
                    <span className={log.level === "error" ? "text-rose-400 font-semibold" : log.level === "warning" ? "text-amber-400" : "text-slate-300"}>
                      {cleanMsg}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
