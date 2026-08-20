"use client";

import React from "react";
import { IconArrowRight, IconMoon } from "./icons";

interface NightRunBannerProps {
  isRunning: boolean;
  isCompleted?: boolean;
  processedCount: number;
  targetCount: number;
  stagedCount: number;
  onViewActivity?: () => void;
  onReviewStaged?: () => void;
  onStartNext?: () => void;
}

export function NightRunBanner({
  isRunning,
  isCompleted,
  processedCount,
  targetCount,
  stagedCount,
  onViewActivity,
  onReviewStaged,
  onStartNext,
}: NightRunBannerProps) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-blue-500/20 bg-gradient-to-r from-[#081220] via-[#0c182c] to-[#08101e] p-5 shadow-2xl backdrop-blur-xl">
      {/* Night Sky Atmospheric Graphic Layer */}
      <div className="pointer-events-none absolute inset-0 opacity-60">
        {/* Subtle Stars */}
        <div className="absolute top-3 left-1/4 w-1 h-1 bg-white rounded-full opacity-70 animate-pulse" />
        <div className="absolute top-6 left-1/2 w-1.5 h-1.5 bg-blue-200 rounded-full opacity-40" />
        <div className="absolute top-4 right-1/3 w-1 h-1 bg-cyan-200 rounded-full opacity-60 animate-pulse" />

        {/* Crescent Moon */}
        <div className="absolute top-4 right-28 opacity-80">
          <svg className="w-9 h-9 text-cyan-200 drop-shadow-[0_0_12px_rgba(56,189,248,0.5)]" viewBox="0 0 24 24" fill="currentColor">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </div>

        {/* Mountain Silhouettes */}
        <svg
          className="absolute bottom-0 right-0 w-full sm:w-2/3 h-16 text-[#050c17]/90 preserve-3d"
          viewBox="0 0 600 120"
          preserveAspectRatio="none"
          fill="currentColor"
        >
          <path d="M0 120 L120 70 L240 100 L380 40 L490 85 L600 50 L600 120 Z" opacity="0.7" />
          <path d="M0 120 L180 85 L320 110 L440 65 L550 95 L600 80 L600 120 Z" opacity="0.9" />
        </svg>
      </div>

      <div className="relative z-10 flex flex-wrap items-center justify-between gap-4">
        {/* Left Status Text */}
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-xl bg-blue-500/15 border border-blue-500/30 flex items-center justify-center text-cyan-300 shadow-[0_0_15px_rgba(56,189,248,0.25)] shrink-0">
            <IconMoon className="w-5 h-5" />
          </div>

          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              {isCompleted ? (
                <>Night Run Complete</>
              ) : isRunning ? (
                <>Night Run Active <span className="h-2 w-2 rounded-full bg-[#2ee8c9] animate-ping" /></>
              ) : (
                <>Night Run Ready</>
              )}
            </h3>

            <p className="text-xs text-slate-300 mt-0.5 max-w-xl">
              {isCompleted ? (
                <>
                  Processed {processedCount} of {targetCount} target applications.{" "}
                  {stagedCount > 0 ? (
                    <strong className="text-amber-300">{stagedCount} items require review.</strong>
                  ) : (
                    "No items require review at this time."
                  )}
                </>
              ) : isRunning ? (
                <>
                  Running during optimal hours for maximum productivity and minimal interruptions. CareerOS will continue until the batch limit is reached.
                </>
              ) : (
                <>Autopilot is configured for autonomous nightly execution with crash isolation.</>
              )}
            </p>
          </div>
        </div>

        {/* Right CTA Actions (Matching Mockup Colors) */}
        <div className="flex items-center gap-3">
          {isCompleted && (
            <>
              {stagedCount > 0 && onReviewStaged && (
                <button
                  onClick={onReviewStaged}
                  style={{
                    background: "#2c1d0c",
                    borderColor: "#f59e0b",
                    color: "#fbbf24",
                    boxShadow: "0 0 18px rgba(245, 158, 11, 0.35)",
                  }}
                  className="px-4 py-2.5 rounded-xl border text-xs font-black transition-all cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
                >
                  Review Staged ({stagedCount})
                </button>
              )}
              {onStartNext && (
                <button
                  onClick={onStartNext}
                  style={{
                    background: "linear-gradient(135deg, rgba(46, 232, 201, 0.15), rgba(56, 189, 248, 0.2))",
                    borderColor: "#2ee8c9",
                    color: "#2ee8c9",
                    boxShadow: "0 0 20px rgba(46, 232, 201, 0.4)",
                  }}
                  className="px-5 py-2.5 rounded-xl border text-xs font-black transition-all cursor-pointer flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98]"
                >
                  <span>Start Next Run</span>
                  <IconArrowRight className="w-4 h-4 text-[#2ee8c9]" />
                </button>
              )}
            </>
          )}

          {!isCompleted && onViewActivity && (
            <button
              onClick={onViewActivity}
              style={{
                background: "rgba(46, 232, 201, 0.12)",
                borderColor: "rgba(46, 232, 201, 0.4)",
                color: "#2ee8c9",
                boxShadow: "0 0 15px rgba(46, 232, 201, 0.25)",
              }}
              className="px-4 py-2.5 rounded-xl border text-xs font-black backdrop-blur-md transition-all cursor-pointer flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98]"
            >
              <span>View Activity Log</span>
              <IconArrowRight className="w-4 h-4 text-[#2ee8c9]" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
