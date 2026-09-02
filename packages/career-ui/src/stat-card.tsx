import { GlassCard } from "./glass-card";
import { cn } from "./lib/cn";

export interface StatCardProps {
  label: string;
  value: string | number;
  hint?: string;
  className?: string;
}

export function StatCard({ label, value, hint, className }: StatCardProps) {
  return (
    <GlassCard className={cn("p-5", className)}>
      <p className="text-xs uppercase tracking-wider text-arsenal-muted">{label}</p>
      <p className="mt-2 text-3xl font-semibold tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-sm text-arsenal-secondary">{hint}</p>}
    </GlassCard>
  );
}
