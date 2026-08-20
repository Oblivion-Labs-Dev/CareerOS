"use client";

import React from "react";
import { IconAlertCircle, IconCheckCircle, IconClock, IconInbox, IconSend } from "./icons";

interface MetricsRibbonProps {
  submitted: number;
  staged: number;
  skipped: number;
  failed: number;
  queueRemaining: number;
  processedCount: number;
}

export function MetricsRibbon({
  submitted,
  staged,
  skipped,
  failed,
  queueRemaining,
  processedCount,
}: MetricsRibbonProps) {
  const baseCount = Math.max(1, processedCount);
  const successPct = Math.round((submitted / baseCount) * 100);
  const stagedPct = Math.round((staged / baseCount) * 100);
  const skipPct = Math.round((skipped / baseCount) * 100);
  const failPct = Math.round((failed / baseCount) * 100);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5 sm:gap-4">
      {/* 1. Submitted Card */}
      <div className="group relative overflow-hidden p-4 rounded-2xl border border-emerald-500/20 bg-gradient-to-b from-[#0b161f] to-[#070e16] shadow-xl hover:border-emerald-500/40 transition-all duration-300">
        <div className="flex items-center justify-between">
          <div className="w-8 h-8 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-[#2ee8c9]">
            <IconSend className="w-4 h-4" />
          </div>
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Submitted</span>
        </div>

        <div className="mt-3 flex items-baseline justify-between">
          <span className="text-2xl sm:text-3xl font-black text-[#2ee8c9] tracking-tight">{submitted}</span>
          <span className="text-[11px] font-medium text-emerald-400/80">{successPct}% success rate</span>
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

      {/* 2. Staged Card */}
      <div className="group relative overflow-hidden p-4 rounded-2xl border border-amber-500/20 bg-gradient-to-b from-[#14120e] to-[#0d0c09] shadow-xl hover:border-amber-500/40 transition-all duration-300">
        <div className="flex items-center justify-between">
          <div className="w-8 h-8 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400">
            <IconClock className="w-4 h-4" />
          </div>
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Staged</span>
        </div>

        <div className="mt-3 flex items-baseline justify-between">
          <span className="text-2xl sm:text-3xl font-black text-amber-400 tracking-tight">{staged}</span>
          <span className="text-[11px] font-medium text-amber-400/80">{stagedPct}% needs review</span>
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
      <div className="group relative overflow-hidden p-4 rounded-2xl border border-indigo-500/20 bg-gradient-to-b from-[#10111e] to-[#0a0a14] shadow-xl hover:border-indigo-500/40 transition-all duration-300">
        <div className="flex items-center justify-between">
          <div className="w-8 h-8 rounded-xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
            <IconInbox className="w-4 h-4" />
          </div>
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Skipped</span>
        </div>

        <div className="mt-3 flex items-baseline justify-between">
          <span className="text-2xl sm:text-3xl font-black text-indigo-400 tracking-tight">{skipped}</span>
          <span className="text-[11px] font-medium text-indigo-400/80">{skipPct}% filtered out</span>
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
      <div className="group relative overflow-hidden p-4 rounded-2xl border border-rose-500/20 bg-gradient-to-b from-[#160e10] to-[#0e080a] shadow-xl hover:border-rose-500/40 transition-all duration-300">
        <div className="flex items-center justify-between">
          <div className="w-8 h-8 rounded-xl bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-rose-400">
            <IconAlertCircle className="w-4 h-4" />
          </div>
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Failed</span>
        </div>

        <div className="mt-3 flex items-baseline justify-between">
          <span className="text-2xl sm:text-3xl font-black text-rose-400 tracking-tight">{failed}</span>
          <span className="text-[11px] font-medium text-rose-400/80">{failPct}% error rate</span>
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
      <div className="group relative overflow-hidden p-4 rounded-2xl border border-cyan-500/20 bg-gradient-to-b from-[#0b1620] to-[#070e16] shadow-xl col-span-2 sm:col-span-1 hover:border-cyan-500/40 transition-all duration-300">
        <div className="flex items-center justify-between">
          <div className="w-8 h-8 rounded-xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center text-[#38bdf8]">
            <IconCheckCircle className="w-4 h-4" />
          </div>
          <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Queue Remaining</span>
        </div>

        <div className="mt-3 flex items-baseline justify-between">
          <span className="text-2xl sm:text-3xl font-black text-[#38bdf8] tracking-tight">{queueRemaining}</span>
          <span className="text-[11px] font-medium text-cyan-400/80">High quality matches</span>
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
  );
}
