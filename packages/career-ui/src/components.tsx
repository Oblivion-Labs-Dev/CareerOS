"use client";

import type { FeaturePriority, FeatureStatus } from "@career-os/core";
import { Badge, GlassCard } from "@arsenal/ui";

const statusVariant: Record<FeatureStatus, "planned" | "progress" | "done"> = {
  planned: "planned",
  "in-progress": "progress",
  done: "done",
};

const priorityVariant: Record<FeaturePriority, "p0" | "p1" | "p2" | "p3"> = {
  P0: "p0",
  P1: "p1",
  P2: "p2",
  P3: "p3",
};

export interface StatusBadgeProps {
  status: FeatureStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <Badge variant={statusVariant[status]}>{status.replace("-", " ")}</Badge>;
}

export interface PriorityBadgeProps {
  priority: FeaturePriority;
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  return <Badge variant={priorityVariant[priority]}>{priority}</Badge>;
}

export interface FeatureCardProps {
  title: string;
  description: string;
  status: FeatureStatus;
  priority: FeaturePriority;
  module: string;
  dependencies: string[];
  technicalNotes: string;
}

export function FeatureCard({
  title,
  description,
  status,
  priority,
  module,
  dependencies,
  technicalNotes,
}: FeatureCardProps) {
  return (
    <GlassCard className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-base font-semibold">{title}</h3>
        <div className="flex flex-wrap gap-1.5">
          <PriorityBadge priority={priority} />
          <StatusBadge status={status} />
        </div>
      </div>
      <p className="text-sm text-arsenal-secondary">{description}</p>
      <div className="text-xs text-arsenal-muted">{module}</div>
      {dependencies.length > 0 && (
        <div className="text-xs text-arsenal-muted">Depends on: {dependencies.join(", ")}</div>
      )}
      <p className="text-xs text-arsenal-muted">{technicalNotes}</p>
    </GlassCard>
  );
}

export { PageHeader, StatCard } from "@arsenal/ui";
export type { PageHeaderProps } from "@arsenal/ui";
export type { StatCardProps } from "@arsenal/ui";
