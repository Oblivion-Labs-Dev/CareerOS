"use client";

import { cn } from "@arsenal/ui";

export interface FilterChipProps {
  label: string;
  active?: boolean;
  count?: number;
  onClick?: () => void;
  className?: string;
}

export function FilterChip({ label, active = false, count, onClick, className }: FilterChipProps) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[0.65rem] font-semibold transition",
        active
          ? "border-arsenal-accent bg-arsenal-accent/10 text-arsenal-accent"
          : "border-arsenal-border bg-arsenal-surface text-arsenal-secondary hover:border-arsenal-border-strong hover:text-arsenal-primary",
        className,
      )}
      onClick={onClick}
      aria-pressed={active}
    >
      {label}
      {typeof count === "number" ? (
        <span className="rounded-full bg-arsenal-elevated px-1.5 py-0.5 text-[0.58rem] tabular-nums">
          {count}
        </span>
      ) : null}
    </button>
  );
}
