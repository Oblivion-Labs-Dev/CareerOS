"use client";

import React, { useState } from "react";
import {
  IconActivity,
  IconCpu,
  IconDatabase,
  IconGlobe,
  IconLayers,
  IconRefresh,
  IconShieldCheck,
  IconWrench,
} from "./icons";

interface SubsystemStatus {
  name: string;
  status: "healthy" | "recovering" | "degraded";
  icon: React.ComponentType<{ className?: string }>;
  details: string;
}

interface SystemHealthPanelProps {
  runnerStatus?: string;
  repairCount?: number;
  lastRepairEvent?: {
    summary: string;
    timestamp: string;
    adapter?: string;
  } | null;
}

export function SystemHealthPanel({
  runnerStatus = "RUNNING",
  repairCount = 0,
  lastRepairEvent,
}: SystemHealthPanelProps) {
  const [showDetails, setShowDetails] = useState(false);

  const subsystems: SubsystemStatus[] = [
    {
      name: "Application Runner",
      status: runnerStatus === "RECOVERING" ? "recovering" : "healthy",
      icon: IconActivity,
      details: "Async event-loop batch coordinator",
    },
    {
      name: "Browser Engine",
      status: "healthy",
      icon: IconGlobe,
      details: "Playwright chromium isolated contexts",
    },
    {
      name: "AI Assistant (Qwen)",
      status: "healthy",
      icon: IconCpu,
      details: "Local Ollama Qwen grounded inference",
    },
    {
      name: "Repair Engine",
      status: repairCount > 0 ? "healthy" : "healthy",
      icon: IconWrench,
      details: "Level 1-3 self-healing controller",
    },
    {
      name: "Database (SQLite)",
      status: "healthy",
      icon: IconDatabase,
      details: "Isolated session scopes & atomic locks",
    },
    {
      name: "ATS Adapters",
      status: "healthy",
      icon: IconLayers,
      details: "Workday, Greenhouse, Lever, Ashby",
    },
  ];

  return (
    <div className="relative overflow-hidden p-5 rounded-2xl border border-white/10 bg-gradient-to-b from-[#0c131e] via-[#090f18] to-[#060a10] shadow-xl backdrop-blur-xl space-y-4">
      {/* Panel Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
          <h3 className="text-xs font-bold uppercase tracking-widest text-slate-200">System Health</h3>
        </div>
        <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/25">
          All systems operational
        </span>
      </div>

      {/* Subsystems List */}
      <div className="space-y-2 text-xs">
        {subsystems.map((sys) => {
          const SysIcon = sys.icon;
          return (
            <div
              key={sys.name}
              className="flex items-center justify-between p-2 rounded-xl bg-[#060b12] border border-white/5 hover:border-white/10 transition-colors"
            >
              <div className="flex items-center gap-2.5">
                <div className="text-slate-400">
                  <SysIcon className="w-3.5 h-3.5" />
                </div>
                <span className="text-slate-300 font-medium">{sys.name}</span>
              </div>

              <div className="flex items-center gap-1.5">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    sys.status === "healthy"
                      ? "bg-emerald-400"
                      : sys.status === "recovering"
                      ? "bg-amber-400 animate-pulse"
                      : "bg-rose-400"
                  }`}
                />
                <span className="text-[11px] font-semibold text-slate-400 capitalize">
                  {sys.status}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Self-Healing Visibility Event */}
      {lastRepairEvent ? (
        <div className="p-3 rounded-xl bg-[#091722] border border-[#2ee8c9]/30 text-xs space-y-1">
          <div className="flex items-center justify-between text-[11px] text-[#2ee8c9] font-bold">
            <span className="flex items-center gap-1.5">
              <IconRefresh className="w-3 h-3 animate-spin" />
              Autonomous Self-Healing
            </span>
            <span className="text-slate-400 font-normal">{lastRepairEvent.timestamp}</span>
          </div>
          <p className="text-[11px] text-slate-300">
            {lastRepairEvent.summary}
          </p>
        </div>
      ) : (
        <div className="p-3 rounded-xl bg-[#070d16] border border-white/5 text-xs flex items-center justify-between text-slate-400">
          <span className="flex items-center gap-1.5">
            <IconShieldCheck className="w-3.5 h-3.5 text-[#2ee8c9]" />
            Crash isolation & recovery active
          </span>
          <span className="text-[10px] font-mono text-slate-500">Level 3 Ready</span>
        </div>
      )}

      {/* Diagnostic Modal Trigger */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-[11px] font-semibold transition-all cursor-pointer text-center"
      >
        {showDetails ? "Hide Diagnostics" : "View System Diagnostics"}
      </button>

      {showDetails && (
        <div className="pt-2 border-t border-white/5 space-y-1.5 text-[11px] font-mono text-slate-400">
          <div>Worker ID: <strong className="text-slate-200">worker_autopilot_main</strong></div>
          <div>Sandboxed Tree: <strong className="text-slate-200">career-os-repairs/</strong></div>
          <div>Submission Guard: <strong className="text-emerald-400">Active (ALLOW_REAL_SUBMISSION)</strong></div>
        </div>
      )}
    </div>
  );
}
