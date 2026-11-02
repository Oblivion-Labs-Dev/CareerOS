"use client";

import { GlassCard } from "./glass-card";

interface TimelineCardProps {
  year: string;
  title: string;
  description: string;
  active?: boolean;
}

export function TimelineCard({ year, title, description, active }: TimelineCardProps) {
  return (
    <GlassCard className={active ? "border-arsenal-accent/40 shadow-arsenal-glow" : undefined}>
      <span className="text-xs font-medium text-arsenal-accent">{year}</span>
      <h3 className="mt-2 font-semibold">{title}</h3>
      <p className="mt-2 text-sm text-arsenal-secondary">{description}</p>
    </GlassCard>
  );
}
