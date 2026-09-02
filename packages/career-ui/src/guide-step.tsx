"use client";

import { type ReactNode } from "react";
import { Tooltip } from "./tooltip";
import { cn } from "./lib/cn";

export interface GuideStepProps {
  id: string;
  step: number;
  title: string;
  summary: string;
  tooltip?: string;
  children: ReactNode;
  className?: string;
}

export function GuideStep({ id, step, title, summary, tooltip, children, className }: GuideStepProps) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={cn("rounded-arsenal border border-arsenal-border bg-arsenal-surface/50 p-6", className)}
    >
      <div className="mb-5 flex gap-4">
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-arsenal-accent/40 bg-arsenal-accent/10 text-sm font-bold text-arsenal-accent"
          aria-hidden
        >
          {step}
        </span>
        <div>
          <h2 id={`${id}-title`} className="flex items-center gap-1 text-xl font-semibold">
            {title}
            {tooltip ? <Tooltip content={tooltip} label={title} /> : null}
          </h2>
          <p className="mt-1 text-sm text-arsenal-secondary">{summary}</p>
        </div>
      </div>
      <div>{children}</div>
    </section>
  );
}
