"use client";

import { cn } from "./lib/cn";
import { type ReactNode } from "react";

export function OrbBackground({ className }: { className?: string }) {
  return (
    <div className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)} aria-hidden>
      <div className="absolute -left-1/4 top-0 h-[500px] w-[500px] rounded-full bg-arsenal-accent/20 blur-[120px]" />
      <div className="absolute -right-1/4 top-1/3 h-[400px] w-[400px] rounded-full bg-orange-600/12 blur-[100px]" />
      <div className="absolute bottom-0 left-1/3 h-[320px] w-[320px] rounded-full bg-amber-500/10 blur-[90px]" />
    </div>
  );
}

export function GridBackground({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 bg-[linear-gradient(var(--arsenal-border)_1px,transparent_1px),linear-gradient(90deg,var(--arsenal-border)_1px,transparent_1px)] bg-[size:64px_64px] [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)] opacity-30",
        className,
      )}
      aria-hidden
    />
  );
}

export function GradientBorder({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "rounded-arsenal-lg bg-gradient-to-br from-arsenal-accent/50 via-orange-600/35 to-amber-500/30 p-px",
        className,
      )}
    >
      <div className="rounded-arsenal-lg bg-arsenal-surface">{children}</div>
    </div>
  );
}
