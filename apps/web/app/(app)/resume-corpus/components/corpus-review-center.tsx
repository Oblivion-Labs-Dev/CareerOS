"use client";

import { SegmentedControl } from "@arsenal/ui";
import { useMemo, useState } from "react";
import { ConcernCard, CorpusEmptyState, FilterChip } from "@career-os/ui/corpus";
import type { CorpusRecord } from "../corpus-model";
import { mapReviewerConcern } from "../corpus-quality";
import { QualityStatusBadge } from "./corpus-quality-ui";
import styles from "../resume-corpus.module.css";

const REVIEWER_PERSONAS = [
  "Recruiter",
  "Hiring manager",
  "Senior engineer",
  "Staff engineer",
  "Principal engineer",
  "Bar raiser",
  "ATS",
  "Resume writer",
  "Devil's advocate",
  "Security reviewer",
  "SRE reviewer",
  "AI infrastructure reviewer",
] as const;

interface CorpusReviewCenterProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string, sectionId?: string) => void;
}

export function CorpusReviewCenter({ records, onSelectRecord }: CorpusReviewCenterProps) {
  const [persona, setPersona] = useState<string>("all");
  const [severity, setSeverity] = useState<string>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [view, setView] = useState<"concerns" | "rejection">("concerns");

  const concerns = useMemo(
    () =>
      records.flatMap((record) =>
        record.concerns.map((concern) => {
          const mapped = mapReviewerConcern(record, concern);
          return {
            ...concern,
            recordId: record.id,
            recordTitle: record.title,
            whyItMatters: mapped.whyItMatters,
            question: mapped.question,
            response: mapped.response,
            suggestedChange: mapped.suggestedChange,
            resolutionStatus: mapped.resolutionStatus,
            resumeImpact: mapped.resumeImpact,
            relatedBullet: mapped.relatedBullet,
          };
        }),
      ),
    [records],
  );

  const filtered = concerns.filter((concern) => {
    if (persona !== "all" && !concern.reviewer.toLowerCase().includes(persona.toLowerCase().split(" ")[0] ?? "")) return false;
    if (severity !== "all" && concern.severity !== severity) return false;
    if (view === "rejection" && concern.severity !== "critical" && concern.severity !== "high") return false;
    return true;
  });

  const openCount = concerns.filter((concern) => concern.status === "unanswered" || concern.status === "investigating").length;

  if (records.length === 0) {
    return (
      <CorpusEmptyState
        title="No reviewer intelligence yet"
        description="Reviewer concerns are generated as you structure accomplishments. Add stories to surface risks early."
      />
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Review Center</div>
          <h1>Reviewer intelligence</h1>
          <p>See what could still get you rejected — organized by persona, severity, and resolution status.</p>
        </div>
        <SegmentedControl
          label="Review view"
          value={view}
          onValueChange={(value) => setView(value as "concerns" | "rejection")}
          options={[
            { value: "concerns", label: "All concerns" },
            { value: "rejection", label: "Rejection risks" },
          ]}
        />
      </header>

      <div className={styles.toolbar}>
        <div className={styles.toolbarGroup}>
          <FilterChip label="All personas" active={persona === "all"} count={concerns.length} onClick={() => setPersona("all")} />
          {REVIEWER_PERSONAS.map((reviewer) => {
            const count = concerns.filter((concern) => concern.reviewer.toLowerCase().includes(reviewer.toLowerCase().split(" ")[0] ?? "")).length;
            if (count === 0) return null;
            return (
              <FilterChip key={reviewer} label={reviewer} active={persona === reviewer} count={count} onClick={() => setPersona(reviewer)} />
            );
          })}
        </div>
        <select className={styles.savedViewSelect} value={severity} onChange={(event) => setSeverity(event.currentTarget.value)} aria-label="Severity filter">
          <option value="all">All severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {openCount > 0 ? (
        <div className={styles.warningRow} role="status">
          <span><strong>{openCount} open concern{openCount === 1 ? "" : "s"} need attention</strong> — resolve high-severity items before using related bullets on a resume.</span>
        </div>
      ) : (
        <div className={styles.panel} role="status">
          <div className={styles.panelHeader}>
            <h3>No open critical concerns</h3>
            <p>Keep strengthening evidence and metrics to maintain readiness.</p>
          </div>
        </div>
      )}

      <div className={styles.cardGrid}>
        {filtered.length === 0 ? (
          <CorpusEmptyState title="No concerns match these filters" description="Try another persona or severity level." />
        ) : (
          filtered.map((concern) => (
            <div key={concern.id} className={styles.reviewConcernWrap}>
              <ConcernCard
                concern={concern}
                expanded={expandedId === concern.id}
                onToggle={() => setExpandedId((current) => (current === concern.id ? null : concern.id))}
                onSelectRecord={() => onSelectRecord(concern.recordId, "concerns")}
              />
              {expandedId === concern.id ? (
                <div className={styles.reviewConcernMeta}>
                  <QualityStatusBadge status={concern.resolutionStatus} />
                  <span>{concern.resumeImpact} resume impact</span>
                  <span>Related bullet: {concern.relatedBullet}</span>
                  <span>Related question: {concern.question ?? "No linked question yet"}</span>
                  <span>Existing answer: {concern.response ?? "Unanswered"}</span>
                  <span>Evidence: {records.find((record) => record.id === concern.recordId)?.evidence.map((item) => item.name).join(", ") || "None linked"}</span>
                  <button type="button" className={styles.textButton} onClick={() => onSelectRecord(concern.recordId, "concerns")}>Resolve in accomplishment →</button>
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
