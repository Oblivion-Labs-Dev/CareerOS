"use client";

import { type ReactNode } from "react";
import { GlassCard } from "./glass-card";
import { cn } from "./lib/cn";

interface BentoCardProps {
  title: string;
  description: string;
  icon?: ReactNode;
  className?: string;
  span?: "1" | "2";
}

export function BentoCard({ title, description, icon, className, span = "1" }: BentoCardProps) {
  return (
    <GlassCard
      glow
      className={cn(
        "group relative overflow-hidden",
        span === "2" && "md:col-span-2",
        className,
      )}
    >
      <div className="pointer-events-none absolute -right-8 -top-8 h-32 w-32 rounded-full bg-arsenal-accent/10 blur-3xl transition-all duration-500 group-hover:bg-arsenal-accent/20" />
      {icon && <div className="mb-4 text-arsenal-accent">{icon}</div>}
      <h3 className="text-lg font-semibold text-arsenal-primary">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-arsenal-secondary">{description}</p>
    </GlassCard>
  );
}
