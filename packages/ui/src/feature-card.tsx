"use client";

import { type ReactNode } from "react";
import { GlassCard } from "./glass-card";
import { cn } from "./lib/cn";

interface FeatureCardProps {
  title: string;
  description: string;
  badge?: string;
  children?: ReactNode;
  className?: string;
}

export function FeatureCard({ title, description, badge, children, className }: FeatureCardProps) {
  return (
    <GlassCard className={cn("flex flex-col gap-3", className)}>
      {badge && (
        <span className="w-fit rounded-full border border-arsenal-border px-2.5 py-0.5 text-xs text-arsenal-accent">
          {badge}
        </span>
      )}
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="text-sm text-arsenal-secondary">{description}</p>
      {children}
    </GlassCard>
  );
}
