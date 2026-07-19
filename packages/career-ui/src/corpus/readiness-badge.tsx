"use client";

import { Badge } from "@arsenal/ui";
import type { CorpusReadiness } from "./types";

const READINESS_VARIANT: Record<CorpusReadiness, "planned" | "progress" | "done" | "p0"> = {
  draft: "planned",
  "needs-input": "p0",
  review: "progress",
  ready: "done",
};

const READINESS_LABEL: Record<CorpusReadiness, string> = {
  draft: "Draft",
  "needs-input": "Needs input",
  review: "In review",
  ready: "Resume ready",
};

export interface ReadinessBadgeProps {
  readiness: CorpusReadiness;
  className?: string;
}

export function ReadinessBadge({ readiness, className }: ReadinessBadgeProps) {
  return (
    <Badge variant={READINESS_VARIANT[readiness]} className={className}>
      {READINESS_LABEL[readiness]}
    </Badge>
  );
}
