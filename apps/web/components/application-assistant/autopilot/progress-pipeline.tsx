"use client";

import React from "react";
import { IconCheck, IconSearch, IconSend, IconShieldCheck, IconStar } from "./icons";

export type PipelineStepKey = "discover" | "score" | "apply" | "verify" | "complete";

interface ProgressPipelineProps {
  currentStep?: string;
  isRunning: boolean;
  isCompleted?: boolean;
}

const PIPELINE_STEPS: { key: PipelineStepKey; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { key: "discover", label: "Discover", icon: IconSearch },
  { key: "score", label: "Score", icon: IconStar },
  { key: "apply", label: "Apply", icon: IconSend },
  { key: "verify", label: "Verify", icon: IconShieldCheck },
  { key: "complete", label: "Complete", icon: IconCheck },
];

function stepIndexFromStatus(status?: string, isCompleted?: boolean): number {
  if (isCompleted) return 4;
  if (!status) return 0;
  const s = status.toUpperCase();
  if (s.includes("PAGE_OPENED") || s.includes("FORM_DISCOVERED")) return 2; // Apply
  if (s.includes("VERIF") || s.includes("SUBMIT")) return 3; // Verify
  if (s.includes("SCORE") || s.includes("RANK")) return 1; // Score
  if (s.includes("COMPLET")) return 4;
  return 0; // Discover
}

export function ProgressPipeline({ currentStep, isRunning, isCompleted }: ProgressPipelineProps) {
  const activeIdx = stepIndexFromStatus(currentStep, isCompleted);

  return (
    <div className="w-full pt-1">
      <div className="flex items-center justify-between relative">
        {PIPELINE_STEPS.map((step, idx) => {
          const StepIcon = step.icon;
          const isDone = isCompleted || (isRunning && idx < activeIdx);
          const isActive = isRunning && idx === activeIdx;
          const isPending = !isDone && !isActive;

          return (
            <React.Fragment key={step.key}>
              {/* Step Connector Line */}
              {idx > 0 && (
                <div className="flex-1 h-[2px] mx-2 relative overflow-hidden bg-slate-800/80 rounded-full">
                  <div
                    className={`h-full transition-all duration-500 rounded-full ${
                      idx <= activeIdx
                        ? "bg-gradient-to-r from-[#2ee8c9] to-[#38bdf8] shadow-[0_0_8px_rgba(46,232,201,0.4)]"
                        : "bg-transparent"
                    }`}
                    style={{ width: idx <= activeIdx ? "100%" : "0%" }}
                  />
                  {isActive && (
                    <div className="absolute inset-0 bg-[#2ee8c9]/40 animate-pulse" />
                  )}
                </div>
              )}

              {/* Step Node */}
              <div className="flex flex-col items-center gap-1.5 group cursor-default">
                <div
                  className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex items-center justify-center border transition-all duration-300 ${
                    isDone
                      ? "bg-emerald-500/15 border-emerald-500/40 text-[#2ee8c9] shadow-[0_0_12px_rgba(46,232,201,0.25)]"
                      : isActive
                      ? "bg-[#0f2430] border-[#2ee8c9] text-[#2ee8c9] shadow-[0_0_16px_rgba(46,232,201,0.5)] scale-110"
                      : "bg-[#0b121c] border-white/10 text-slate-500"
                  }`}
                >
                  <StepIcon className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${isActive ? "animate-pulse" : ""}`} />
                </div>
                <span
                  className={`text-[11px] sm:text-xs font-semibold transition-colors ${
                    isDone
                      ? "text-slate-300"
                      : isActive
                      ? "text-[#2ee8c9] font-bold"
                      : "text-slate-500"
                  }`}
                >
                  {step.label}
                </span>
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
