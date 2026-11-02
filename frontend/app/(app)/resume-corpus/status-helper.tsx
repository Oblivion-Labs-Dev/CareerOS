"use client";

import React from "react";

export type CoreStatus = "missing" | "weak" | "partial" | "strong" | "ready" | "na" | "verify";

export interface StatusDetail {
  status: CoreStatus;
  label: string;
  colorClass: string;
  borderColorClass: string;
  bgColorClass: string;
  icon: string;
  description: string;
}

export function getStatusDetails(status: CoreStatus): StatusDetail {
  switch (status) {
    case "missing":
      return {
        status: "missing",
        label: "Missing",
        colorClass: "text-red-400",
        borderColorClass: "border-red-500",
        bgColorClass: "bg-red-950/20",
        icon: "🔴",
        description: "No answer exists or required information is absent.",
      };
    case "weak":
      return {
        status: "weak",
        label: "Needs detail",
        colorClass: "text-amber-400",
        borderColorClass: "border-amber-500",
        bgColorClass: "bg-amber-950/20",
        icon: "⚠️",
        description: "Answer exists but lacks specific detail or tradeoffs.",
      };
    case "partial":
      return {
        status: "partial",
        label: "Partial",
        colorClass: "text-blue-400",
        borderColorClass: "border-blue-500",
        bgColorClass: "bg-blue-950/20",
        icon: "🔵",
        description: "Some required information exists but important parts are incomplete.",
      };
    case "strong":
      return {
        status: "strong",
        label: "Strong",
        colorClass: "text-green-400",
        borderColorClass: "border-green-500",
        bgColorClass: "bg-green-950/20",
        icon: "🟢",
        description: "Answer is clear, technical reasoning is credible, and metrics are specific.",
      };
    case "ready":
      return {
        status: "ready",
        label: "Interview ready",
        colorClass: "text-emerald-400",
        borderColorClass: "border-emerald-500",
        bgColorClass: "bg-emerald-950/20",
        icon: "✅",
        description: "Answer is fully complete, reviewed, and practiced.",
      };
    case "na":
      return {
        status: "na",
        label: "Not applicable",
        colorClass: "text-slate-500",
        borderColorClass: "border-slate-800",
        bgColorClass: "bg-slate-900/10",
        icon: "🔘",
        description: "This category does not apply to this accomplishment.",
      };
    case "verify":
      return {
        status: "verify",
        label: "Verify",
        colorClass: "text-purple-400",
        borderColorClass: "border-purple-500",
        bgColorClass: "bg-purple-950/20",
        icon: "🔍",
        description: "Metric is entered but needs validation or source check.",
      };
  }
}

export function StatusIndicator({ status }: { status: CoreStatus }) {
  const details = getStatusDetails(status);
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold border ${details.colorClass} ${details.borderColorClass} ${details.bgColorClass}`} title={details.description}>
      <span aria-hidden>{details.icon}</span>
      <span>{details.label}</span>
    </span>
  );
}
