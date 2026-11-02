"use client";

import { useMemo } from "react";
import {
  ATS_LABEL,
  type AtsSource,
  type Seniority,
  SENIORITY_LABEL,
  SENIORITY_ORDER,
  triageSignals,
  type TriageJob,
} from "@/lib/inbox-triage";

type DiscoverTriageBarProps = {
  jobs: TriageJob[];
  atsFilter: AtsSource | "all";
  seniorityFilter: Seniority | "all";
  maxAgeDays: number | "all";
  shortlist: Set<string>;
  onAtsFilter: (value: AtsSource | "all") => void;
  onSeniorityFilter: (value: Seniority | "all") => void;
  onMaxAgeDays: (value: number | "all") => void;
  onToggleShortlist: (jobId: string) => void;
  onClearShortlist: () => void;
  onScoreShortlist: () => void;
  scoringShortlist?: boolean;
};

const AGE_OPTIONS: Array<{ value: number | "all"; label: string }> = [
  { value: "all", label: "Any age" },
  { value: 1, label: "24h" },
  { value: 3, label: "3d" },
  { value: 7, label: "7d" },
  { value: 14, label: "14d" },
];

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={active ? "phase-pill" : "btn btn-sm btn-secondary"}
      style={{ padding: "0.25rem 0.65rem", fontSize: "0.8rem" }}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function DiscoverTriageBar({
  jobs,
  atsFilter,
  seniorityFilter,
  maxAgeDays,
  shortlist,
  onAtsFilter,
  onSeniorityFilter,
  onMaxAgeDays,
  onToggleShortlist,
  onClearShortlist,
  onScoreShortlist,
  scoringShortlist,
}: DiscoverTriageBarProps) {
  const presentAts = useMemo(() => {
    const set = new Set<AtsSource>();
    jobs.forEach((job) => set.add(triageSignals(job).ats));
    return Array.from(set).filter((item) => item !== "other");
  }, [jobs]);

  const presentSeniority = useMemo(() => {
    const set = new Set<Seniority>();
    jobs.forEach((job) => {
      const value = triageSignals(job).seniority;
      if (value) set.add(value);
    });
    return SENIORITY_ORDER.filter((item) => set.has(item));
  }, [jobs]);

  return (
    <div className="stack gap-sm" style={{ marginBottom: "0.75rem" }}>
      <div className="flex flex-wrap gap-sm items-center">
        <span className="muted text-sm" style={{ marginRight: "0.25rem" }}>
          Quick filters
        </span>
        <Chip active={atsFilter === "all"} onClick={() => onAtsFilter("all")}>
          All ATS
        </Chip>
        {presentAts.map((ats) => (
          <Chip key={ats} active={atsFilter === ats} onClick={() => onAtsFilter(ats)}>
            {ATS_LABEL[ats]}
          </Chip>
        ))}
        <span className="muted text-sm" style={{ margin: "0 0.25rem" }}>
          ·
        </span>
        <Chip active={seniorityFilter === "all"} onClick={() => onSeniorityFilter("all")}>
          All levels
        </Chip>
        {presentSeniority.map((level) => (
          <Chip key={level} active={seniorityFilter === level} onClick={() => onSeniorityFilter(level)}>
            {SENIORITY_LABEL[level]}
          </Chip>
        ))}
        <select
          className="input"
          style={{ width: "auto", minWidth: "5.5rem", padding: "0.25rem 0.5rem", fontSize: "0.8rem" }}
          value={String(maxAgeDays)}
          onChange={(event) => {
            const raw = event.target.value;
            onMaxAgeDays(raw === "all" ? "all" : Number(raw));
          }}
        >
          {AGE_OPTIONS.map((option) => (
            <option key={String(option.value)} value={String(option.value)}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {shortlist.size > 0 ? (
        <div
          className="flex flex-wrap gap-sm items-center justify-between panel"
          style={{ padding: "0.65rem 0.85rem" }}
        >
          <span className="text-sm">
            Shortlist: <strong>{shortlist.size}</strong> role{shortlist.size === 1 ? "" : "s"}
          </span>
          <div className="flex gap-sm">
            <button type="button" className="btn btn-sm btn-secondary" onClick={onClearShortlist}>
              Clear
            </button>
            <button type="button" className="btn btn-sm btn-primary" disabled={scoringShortlist} onClick={onScoreShortlist}>
              {scoringShortlist ? "Scoring…" : "Score shortlist"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ShortlistToggle({
  jobId,
  shortlist,
  onToggle,
}: {
  jobId: string;
  shortlist: Set<string>;
  onToggle: (jobId: string) => void;
}) {
  const active = shortlist.has(jobId);
  return (
    <button
      type="button"
      className={active ? "btn btn-sm btn-primary" : "btn btn-sm btn-secondary"}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onToggle(jobId);
      }}
    >
      {active ? "Shortlisted" : "Shortlist"}
    </button>
  );
}
