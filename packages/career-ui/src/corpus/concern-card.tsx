"use client";

import { Badge, cn } from "@arsenal/ui";
import type { ConcernCardData } from "./types";

const SEVERITY_VARIANT = {
  low: "planned",
  medium: "progress",
  high: "p1",
  critical: "p0",
} as const;

const STATUS_LABEL = {
  unanswered: "Unanswered",
  investigating: "Investigating",
  answered: "Answered",
  resolved: "Resolved",
  "not-applicable": "Not applicable",
  "intentionally-omitted": "Intentionally omitted",
} as const;

export interface ConcernCardProps {
  concern: ConcernCardData;
  expanded?: boolean;
  onToggle?: () => void;
  onSelectRecord?: () => void;
  className?: string;
}

export function ConcernCard({
  concern,
  expanded = false,
  onToggle,
  onSelectRecord,
  className,
}: ConcernCardProps) {
  return (
    <article
      className={cn(
        "rounded-xl border border-arsenal-border bg-arsenal-surface p-3.5 transition hover:border-arsenal-border-strong",
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          <Badge variant={SEVERITY_VARIANT[concern.severity]}>{concern.severity}</Badge>
          <Badge variant="planned">{concern.reviewer}</Badge>
          <Badge variant="progress">{STATUS_LABEL[concern.status]}</Badge>
        </div>
        {concern.recordTitle && onSelectRecord ? (
          <button
            type="button"
            className="text-[0.62rem] font-semibold text-arsenal-accent hover:underline"
            onClick={onSelectRecord}
          >
            {concern.recordTitle}
          </button>
        ) : null}
      </div>

      <button
        type="button"
        className="mt-2 w-full text-left"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <p className="mt-2 text-sm font-medium leading-snug text-arsenal-primary">{concern.concern}</p>
      </button>

      {expanded ? (
        <div className="mt-3 grid gap-2 border-t border-arsenal-border pt-3 text-xs text-arsenal-secondary">
          {concern.whyItMatters ? (
            <div>
              <span className="font-bold uppercase tracking-wide text-arsenal-muted">Why it matters</span>
              <p className="mt-1 leading-relaxed">{concern.whyItMatters}</p>
            </div>
          ) : null}
          {concern.question ? (
            <div>
              <span className="font-bold uppercase tracking-wide text-arsenal-muted">Question to answer</span>
              <p className="mt-1 leading-relaxed">{concern.question}</p>
            </div>
          ) : null}
          {concern.response ? (
            <div>
              <span className="font-bold uppercase tracking-wide text-arsenal-muted">Your response</span>
              <p className="mt-1 leading-relaxed">{concern.response}</p>
            </div>
          ) : null}
          {concern.suggestedChange ? (
            <div>
              <span className="font-bold uppercase tracking-wide text-arsenal-muted">Suggested resume change</span>
              <p className="mt-1 leading-relaxed">{concern.suggestedChange}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
