"use client";

import React from "react";
import {
  IconAlertCircle,
  IconCheckCircle,
  IconClock,
  IconInbox,
  IconSend,
} from "./icons";

interface ConcurrencyMetrics {
  activeWorkers: number;
  totalWorkers: number;
  avgJobTimeSec: number;
  throughputPerMin: number;
  lockContentionCount: number;
  selfHealingRoundsCompleted: number;
}

interface SelfHealingInfo {
  status: string;
  currentRound: number;
  maxRounds: number;
  lastPatchSummary: string;
  patchesApplied: number;
}

interface MetricsRibbonProps {
  submitted: number;
  staged: number;
  skipped: number;
  failed: number;
  queueRemaining: number;
  processedCount: number;
  concurrencyMetrics?: ConcurrencyMetrics;
  selfHealing?: SelfHealingInfo;
  onSelectCategory?: (category: "SUBMITTED" | "STAGED" | "SKIPPED" | "FAILED" | "QUEUED") => void;
}

export function MetricsRibbon({
  submitted,
  staged,
  skipped,
  failed,
  queueRemaining,
  processedCount,
  concurrencyMetrics,
  selfHealing,
  onSelectCategory,
}: MetricsRibbonProps) {

  const baseCount = Math.max(1, processedCount);
  const successPct = Math.round((submitted / baseCount) * 100);
  const stagedPct = Math.round((staged / baseCount) * 100);
  const skipPct = Math.round((skipped / baseCount) * 100);
  const failPct = Math.round((failed / baseCount) * 100);

  const handleCardClick = (category: "SUBMITTED" | "STAGED" | "SKIPPED" | "FAILED" | "QUEUED") => {
    if (onSelectCategory) {
      onSelectCategory(category);
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5 sm:gap-4">
        {/* 1. Submitted Card */}
        <div
          onClick={() => handleCardClick("SUBMITTED")}
          className="group relative overflow-hidden p-4 rounded-2xl border transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98] border-emerald-500/20 bg-gradient-to-b from-[#0b161f] to-[#070e16] shadow-xl hover:border-emerald-500/50 hover:shadow-[0_0_20px_rgba(46,232,201,0.25)]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-[#2ee8c9]">
              <IconSend className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-[#2ee8c9] transition-colors">
              Submitted
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-[#2ee8c9] tracking-tight">{submitted}</span>
            <span className="text-[11px] font-medium text-emerald-400/80">{successPct}% rate</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 20 Q30 18 60 12 T120 4"
                fill="none"
                stroke="#2ee8c9"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 2. Review Card */}
        <div
          onClick={() => handleCardClick("STAGED")}
          className="group relative overflow-hidden p-4 rounded-2xl border transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98] border-amber-500/20 bg-gradient-to-b from-[#14120e] to-[#0d0c09] shadow-xl hover:border-amber-500/50 hover:shadow-[0_0_20px_rgba(245,158,11,0.25)]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400">
              <IconClock className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-amber-400 transition-colors">
              In Review
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-amber-400 tracking-tight">{staged}</span>
            <span className="text-[11px] font-medium text-amber-400/80">{stagedPct}% review</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 16 Q30 8 60 18 T120 10"
                fill="none"
                stroke="#f59e0b"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 3. Skipped Card */}
        <div
          onClick={() => handleCardClick("SKIPPED")}
          className="group relative overflow-hidden p-4 rounded-2xl border transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98] border-indigo-500/20 bg-gradient-to-b from-[#10111e] to-[#0a0a14] shadow-xl hover:border-indigo-500/50 hover:shadow-[0_0_20px_rgba(99,102,241,0.25)]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              <IconInbox className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-indigo-400 transition-colors">
              Skipped
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-indigo-400 tracking-tight">{skipped}</span>
            <span className="text-[11px] font-medium text-indigo-400/80">{skipPct}% skipped</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 18 Q40 14 80 16 T120 8"
                fill="none"
                stroke="#818cf8"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 4. Failed Card */}
        <div
          onClick={() => handleCardClick("FAILED")}
          className="group relative overflow-hidden p-4 rounded-2xl border transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98] border-rose-500/20 bg-gradient-to-b from-[#160e10] to-[#0e080a] shadow-xl hover:border-rose-500/50 hover:shadow-[0_0_20px_rgba(244,63,94,0.25)]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-rose-400">
              <IconAlertCircle className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-rose-400 transition-colors">
              Failed
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-rose-400 tracking-tight">{failed}</span>
            <span className="text-[11px] font-medium text-rose-400/80">{failPct}% error</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 20 Q40 20 80 16 T120 14"
                fill="none"
                stroke="#f43f5e"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 5. Queue Remaining Card */}
        <div
          onClick={() => handleCardClick("QUEUED")}
          className="group relative overflow-hidden p-4 rounded-2xl border col-span-2 sm:col-span-1 transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98] border-cyan-500/20 bg-gradient-to-b from-[#0b1620] to-[#070e16] shadow-xl hover:border-cyan-500/50 hover:shadow-[0_0_20px_rgba(56,189,248,0.25)]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center text-[#38bdf8]">
              <IconCheckCircle className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-[#38bdf8] transition-colors">
              Queue
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-[#38bdf8] tracking-tight">{queueRemaining}</span>
            <span className="text-[11px] font-medium text-cyan-400/80">Active queue</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 10 Q30 16 60 8 T120 18"
                fill="none"
                stroke="#38bdf8"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>
      </div>



      {/* Concurrency & Self-Healing Metrics Strip */}
      {concurrencyMetrics && (
        <div className="grid grid-cols-3 gap-3 mt-3">
          {/* Active Workers */}
          <div className="p-3 rounded-xl border border-indigo-500/15 bg-gradient-to-b from-[#0e0f1e] to-[#08091a] flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/25 flex items-center justify-center">
              <span className="text-indigo-400 text-sm font-black">{concurrencyMetrics.activeWorkers}</span>
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Active Workers</div>
              <div className="text-xs font-bold text-indigo-300">
                {concurrencyMetrics.activeWorkers}/{concurrencyMetrics.totalWorkers} slots
              </div>
            </div>
          </div>

          {/* Throughput */}
          <div className="p-3 rounded-xl border border-teal-500/15 bg-gradient-to-b from-[#0b1518] to-[#070e12] flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-teal-500/10 border border-teal-500/25 flex items-center justify-center">
              <span className="text-teal-400 text-sm font-black">⚡</span>
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Throughput</div>
              <div className="text-xs font-bold text-teal-300">
                {concurrencyMetrics.throughputPerMin.toFixed(1)} jobs/min
                <span className="text-[10px] text-slate-500 ml-1">
                  (avg {concurrencyMetrics.avgJobTimeSec.toFixed(0)}s)
                </span>
              </div>
            </div>
          </div>

          {/* Self-Healing */}
          <div className="p-3 rounded-xl border border-amber-500/15 bg-gradient-to-b from-[#14120e] to-[#0d0c09] flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/25 flex items-center justify-center">
              <span className="text-amber-400 text-sm font-black">🔧</span>
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Self-Healing</div>
              <div className="text-xs font-bold text-amber-300">
                {selfHealing?.status === "idle" ? (
                  <>
                    {selfHealing.patchesApplied > 0
                      ? `${selfHealing.patchesApplied} patch(es) applied`
                      : "Standby"}
                  </>
                ) : (
                  <span className="animate-pulse">
                    {selfHealing?.status}… (Round {selfHealing?.currentRound}/{selfHealing?.maxRounds})
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
