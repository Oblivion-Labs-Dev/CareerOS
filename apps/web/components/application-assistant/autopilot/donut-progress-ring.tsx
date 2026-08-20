"use client";

import React from "react";

interface DonutProgressRingProps {
  processed: number;
  target: number;
  submitted: number;
  staged: number;
  skipped: number;
  failed: number;
  isCompleted?: boolean;
}

export function DonutProgressRing({
  processed,
  target,
  submitted,
  staged,
  skipped,
  failed,
  isCompleted,
}: DonutProgressRingProps) {
  const safeTarget = Math.max(1, target);
  const percent = Math.min(100, Math.round((processed / safeTarget) * 100));

  // SVG circular arc calculations
  const radius = 54;
  const circumference = 2 * Math.PI * radius;

  // Segment proportions
  const subRatio = submitted / safeTarget;
  const stagedRatio = staged / safeTarget;
  const skipRatio = skipped / safeTarget;
  const failRatio = failed / safeTarget;

  const subLen = subRatio * circumference;
  const stagedLen = stagedRatio * circumference;
  const skipLen = skipRatio * circumference;
  const failLen = failRatio * circumference;

  const subOffset = 0;
  const stagedOffset = -subLen;
  const skipOffset = -(subLen + stagedLen);
  const failOffset = -(subLen + stagedLen + skipLen);

  return (
    <div className="flex flex-col items-center justify-center space-y-4">
      {/* SVG Donut Ring */}
      <div className="relative w-36 h-36 sm:w-40 sm:h-40 flex items-center justify-center">
        <svg className="w-full h-full -rotate-90" viewBox="0 0 140 140">
          {/* Base Track */}
          <circle
            cx="70"
            cy="70"
            r={radius}
            fill="none"
            stroke="rgba(148, 163, 184, 0.08)"
            strokeWidth="10"
          />

          {/* Submitted Arc (Teal) */}
          {submitted > 0 && (
            <circle
              cx="70"
              cy="70"
              r={radius}
              fill="none"
              stroke="#2ee8c9"
              strokeWidth="10"
              strokeDasharray={`${subLen} ${circumference}`}
              strokeDashoffset={subOffset}
              strokeLinecap="round"
              className="transition-all duration-700"
            />
          )}

          {/* Staged Arc (Amber) */}
          {staged > 0 && (
            <circle
              cx="70"
              cy="70"
              r={radius}
              fill="none"
              stroke="#f59e0b"
              strokeWidth="10"
              strokeDasharray={`${stagedLen} ${circumference}`}
              strokeDashoffset={stagedOffset}
              strokeLinecap="round"
              className="transition-all duration-700"
            />
          )}

          {/* Skipped Arc (Purple) */}
          {skipped > 0 && (
            <circle
              cx="70"
              cy="70"
              r={radius}
              fill="none"
              stroke="#818cf8"
              strokeWidth="10"
              strokeDasharray={`${skipLen} ${circumference}`}
              strokeDashoffset={skipOffset}
              strokeLinecap="round"
              className="transition-all duration-700"
            />
          )}

          {/* Failed Arc (Rose) */}
          {failed > 0 && (
            <circle
              cx="70"
              cy="70"
              r={radius}
              fill="none"
              stroke="#f43f5e"
              strokeWidth="10"
              strokeDasharray={`${failLen} ${circumference}`}
              strokeDashoffset={failOffset}
              strokeLinecap="round"
              className="transition-all duration-700"
            />
          )}
        </svg>

        {/* Center Number & Label */}
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center select-none">
          <span className="text-2xl sm:text-3xl font-black text-white tracking-tight">
            {isCompleted ? "100%" : processed}
          </span>
          <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            {isCompleted ? "Complete" : "Processed"}
          </span>
        </div>
      </div>

      {/* Legend Breakdown */}
      <div className="w-full grid grid-cols-2 gap-x-4 gap-y-2 text-xs pt-1 border-t border-white/5">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="w-2 h-2 rounded-full bg-[#2ee8c9]" />
            Submitted
          </span>
          <span className="font-bold font-mono text-slate-200">{submitted}</span>
        </div>

        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="w-2 h-2 rounded-full bg-amber-400" />
            Staged
          </span>
          <span className="font-bold font-mono text-slate-200">{staged}</span>
        </div>

        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="w-2 h-2 rounded-full bg-indigo-400" />
            Skipped
          </span>
          <span className="font-bold font-mono text-slate-200">{skipped}</span>
        </div>

        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-slate-400">
            <span className="w-2 h-2 rounded-full bg-rose-400" />
            Failed
          </span>
          <span className="font-bold font-mono text-slate-200">{failed}</span>
        </div>
      </div>
    </div>
  );
}
