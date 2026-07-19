"use client";

import { InfoTooltip } from "@arsenal/ui";
import type { ReactNode } from "react";

export interface ScoreExplanationProps {
  label: string;
  score: number;
  explanation: string;
  children?: ReactNode;
}

export function ScoreExplanation({ label, score, explanation, children }: ScoreExplanationProps) {
  return (
    <div className="inline-flex items-center gap-1.5">
      {children ?? (
        <span className="text-sm font-semibold tabular-nums text-arsenal-primary">
          {score}
        </span>
      )}
      <InfoTooltip
        label={`${label}: ${score}`}
        content={explanation}
      />
    </div>
  );
}
