"use client";

import { cn } from "@arsenal/ui";
import type { EvidenceItem } from "./types";

export interface EvidenceViewerProps {
  items: EvidenceItem[];
  onSelectRecord?: (recordTitle: string) => void;
  className?: string;
}

export function EvidenceViewer({ items, onSelectRecord, className }: EvidenceViewerProps) {
  if (items.length === 0) {
    return (
      <p className={cn("text-xs text-arsenal-muted", className)}>
        No evidence attached yet. Link dashboards, RFCs, or artifacts that support your claims.
      </p>
    );
  }

  return (
    <ul className={cn("grid gap-2", className)}>
      {items.map((item) => (
        <li
          key={item.id}
          className="flex items-start justify-between gap-3 rounded-lg border border-arsenal-border bg-arsenal-surface p-3"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-arsenal-primary">{item.name}</span>
              <span className="rounded-md border border-arsenal-border px-1.5 py-0.5 text-[0.58rem] uppercase tracking-wide text-arsenal-muted">
                {item.type}
              </span>
            </div>
            {item.description ? (
              <p className="mt-1 text-xs leading-relaxed text-arsenal-secondary">{item.description}</p>
            ) : null}
            {item.recordTitle && onSelectRecord ? (
              <button
                type="button"
                className="mt-1.5 text-[0.62rem] font-semibold text-arsenal-accent hover:underline"
                onClick={() => onSelectRecord(item.recordTitle!)}
              >
                {item.recordTitle}
              </button>
            ) : null}
          </div>
          {item.url ? (
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 text-xs font-semibold text-arsenal-accent hover:underline"
            >
              Open
            </a>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
