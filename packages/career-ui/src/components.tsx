import type { FeaturePriority, FeatureStatus } from "@career-os/core";

const statusClass: Record<FeatureStatus, string> = {
  planned: "cos-badge--planned",
  "in-progress": "cos-badge--progress",
  done: "cos-badge--done",
};

const priorityClass: Record<FeaturePriority, string> = {
  P0: "cos-badge--p0",
  P1: "cos-badge--p1",
  P2: "cos-badge--p2",
  P3: "cos-badge--p3",
};

export interface StatusBadgeProps {
  status: FeatureStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return <span className={`cos-badge ${statusClass[status]}`}>{status.replace("-", " ")}</span>;
}

export interface PriorityBadgeProps {
  priority: FeaturePriority;
}

export function PriorityBadge({ priority }: PriorityBadgeProps) {
  return <span className={`cos-badge ${priorityClass[priority]}`}>{priority}</span>;
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
    <article className="cos-feature-card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem", flexWrap: "wrap" }}>
        <h3>{title}</h3>
        <div className="cos-badge-row">
          <PriorityBadge priority={priority} />
          <StatusBadge status={status} />
        </div>
      </div>
      <p>{description}</p>
      <div className="cos-feature-meta">{module}</div>
      {dependencies.length > 0 && <div className="cos-feature-deps">Depends on: {dependencies.join(", ")}</div>}
      <p className="cos-feature-notes">{technicalNotes}</p>
    </article>
  );
}

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <header className="cos-page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions}
    </header>
  );
}

export interface StatCardProps {
  label: string;
  value: string | number;
  hint?: string;
}

export function StatCard({ label, value, hint }: StatCardProps) {
  return (
    <div className="cos-stat-card">
      <div className="cos-stat-label">{label}</div>
      <div className="cos-stat-value">{value}</div>
      {hint && <div className="cos-stat-hint">{hint}</div>}
    </div>
  );
}
