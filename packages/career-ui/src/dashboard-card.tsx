"use client";

import { GlassCard } from "./glass-card";
import { cn } from "./lib/cn";

interface DashboardCardProps {
  title: string;
  value: string;
  change?: string;
  trend?: "up" | "down" | "neutral";
  className?: string;
}

export function DashboardCard({ title, value, change, trend = "neutral", className }: DashboardCardProps) {
  const trendColor =
    trend === "up" ? "text-arsenal-success bg-arsenal-success/10 border-arsenal-success/20" : trend === "down" ? "text-arsenal-danger bg-arsenal-danger/10 border-arsenal-danger/20" : "text-arsenal-muted bg-arsenal-elevated/50 border-arsenal-border";
  return (
    <GlassCard glow className={cn("p-6 relative overflow-hidden flex flex-col justify-between min-h-[140px]", className)}>
      <div>
        <p className="text-xs font-bold uppercase tracking-widest text-arsenal-muted">{title}</p>
        <p className="mt-3 text-4xl font-extrabold tracking-tight text-arsenal-primary">{value}</p>
      </div>
      {change && (
        <span className={cn("mt-4 self-start inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border", trendColor)}>
          <span className={cn("h-1.5 w-1.5 rounded-full", trend === "up" ? "bg-arsenal-success" : trend === "down" ? "bg-arsenal-danger" : "bg-arsenal-muted")} />
          {change}
        </span>
      )}
    </GlassCard>
  );
}
