"use client";

import { cn, InfoTooltip } from "@arsenal/ui";
import type { SkillDepth, SkillDepthData } from "./types";

const DEPTH_LABEL: Record<SkillDepth, string> = {
  exposure: "Exposure",
  working: "Working knowledge",
  production: "Production experience",
  deep: "Deep expertise",
  leadership: "Technical leadership",
};

const DEPTH_WIDTH: Record<SkillDepth, string> = {
  exposure: "20%",
  working: "40%",
  production: "60%",
  deep: "80%",
  leadership: "100%",
};

const DEPTH_EXPLANATION: Record<SkillDepth, string> = {
  exposure: "Used in learning, prototypes, or limited scope.",
  working: "Can implement and debug with guidance.",
  production: "Shipped and operated in production systems.",
  deep: "Owns design decisions and edge cases for this skill.",
  leadership: "Sets standards and guides others using this skill.",
};

export interface SkillDepthIndicatorProps {
  skill: SkillDepthData;
  onClick?: () => void;
  className?: string;
}

export function SkillDepthIndicator({ skill, onClick, className }: SkillDepthIndicatorProps) {
  return (
    <div
      className={cn(
        "rounded-xl border border-arsenal-border bg-arsenal-surface p-3 text-left transition",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="text-sm font-semibold text-arsenal-primary">{skill.name}</span>
          {skill.group ? (
            <span className="mt-0.5 block text-[0.62rem] text-arsenal-muted">{skill.group}</span>
          ) : null}
        </div>
        <InfoTooltip label={skill.name} content={DEPTH_EXPLANATION[skill.depth]} />
      </div>

      <div className="mt-3">
        <div className="flex items-center justify-between text-[0.62rem] text-arsenal-muted">
          <span>{DEPTH_LABEL[skill.depth]}</span>
          <span>{skill.evidenceCount} evidence · {skill.accomplishmentCount} stories</span>
        </div>
        <div
          className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-arsenal-elevated"
          role="progressbar"
          aria-valuenow={parseInt(DEPTH_WIDTH[skill.depth], 10)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${skill.name} depth: ${DEPTH_LABEL[skill.depth]}`}
        >
          <div
            className="h-full rounded-full bg-arsenal-accent transition-all"
            style={{ width: DEPTH_WIDTH[skill.depth] }}
          />
        </div>
      </div>

      {(skill.yearsUsed || skill.interviewConfidence !== undefined) && (
        <div className="mt-2 flex flex-wrap gap-3 text-[0.62rem] text-arsenal-muted">
          {skill.yearsUsed ? <span>{skill.yearsUsed}y used</span> : null}
          {skill.lastUsed ? <span>Last: {skill.lastUsed}</span> : null}
          {skill.interviewConfidence !== undefined ? (
            <span>Interview confidence: {skill.interviewConfidence}%</span>
          ) : null}
        </div>
      )}
      {onClick ? (
        <button
          type="button"
          className="mt-3 min-h-8 rounded-md border border-arsenal-border px-3 py-1.5 text-xs font-medium text-arsenal-primary transition hover:border-arsenal-border-strong hover:bg-arsenal-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-arsenal-accent"
          onClick={onClick}
        >
          Open source story
        </button>
      ) : null}
    </div>
  );
}
