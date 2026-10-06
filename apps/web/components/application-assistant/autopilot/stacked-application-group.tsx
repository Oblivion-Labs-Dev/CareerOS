"use client";

import React, { useState } from "react";
import type { AutopilotJobRow } from "./job-types";
import type { ReasonMeta } from "./job-presentation";
import { ApplicationCard } from "./application-card";
import styles from "./stacked-application-group.module.css";

export function StackedApplicationGroup({
  reasonKey,
  reasonMeta,
  jobs,
  busy,
  detailId,
  onDetails,
  onApply,
  onAssistedFill,
  onRetry,
  defaultExpanded = false,
}: {
  reasonKey: string;
  reasonMeta: ReasonMeta;
  jobs: AutopilotJobRow[];
  busy: string | null;
  detailId?: string | null;
  onDetails: (job: AutopilotJobRow) => void;
  onApply: (job: AutopilotJobRow) => void;
  onAssistedFill?: (job: AutopilotJobRow) => void;
  onRetry?: (job: AutopilotJobRow) => void;
  defaultExpanded?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded || jobs.length <= 1);
  const [currentIndex, setCurrentIndex] = useState(0);

  // Safeguard index if jobs list shrinks
  const activeIndex = Math.min(currentIndex, Math.max(0, jobs.length - 1));
  const activeJob = jobs[activeIndex] || jobs[0];

  // Company breakdown within this reason stack
  const companyCounts = React.useMemo(() => {
    const map: Record<string, number> = {};
    for (const j of jobs) {
      const name = (j.company || "Unknown").trim();
      map[name] = (map[name] || 0) + 1;
    }
    return Object.entries(map).sort((a, b) => b[1] - a[1]);
  }, [jobs]);

  const topCompanies = companyCounts.slice(0, 5);
  const remainingCompanyCount = companyCounts.length - topCompanies.length;

  if (jobs.length === 0) return null;

  return (
    <section
      className={styles.stackContainer}
      data-tone={reasonMeta.tone}
      aria-label={`${reasonMeta.label} (${jobs.length} applications)`}
    >
      <header className={styles.stackHeader}>
        <div className={styles.stackMeta}>
          <div className={styles.stackTitleRow}>
            <span className={styles.stackIcon} aria-hidden="true">
              {reasonMeta.icon}
            </span>
            <h3 className={styles.stackTitle}>{reasonMeta.label}</h3>
            <span className={styles.stackCountPill}>
              {jobs.length} {jobs.length === 1 ? "application" : "stacked"}
            </span>
          </div>
          <p className={styles.stackExplanation}>{reasonMeta.explanation}</p>
        </div>

        {jobs.length > 1 && (
          <div className={styles.stackActions}>
            <button
              type="button"
              className={styles.expandBtn}
              onClick={() => setIsExpanded(!isExpanded)}
              aria-expanded={isExpanded}
            >
              {isExpanded ? (
                <>
                  <span>▲</span> Collapse stack
                </>
              ) : (
                <>
                  <span>▼</span> Expand all ({jobs.length})
                </>
              )}
            </button>
          </div>
        )}
      </header>

      {/* Companies summary pills */}
      {companyCounts.length > 1 && (
        <div className={styles.companyPillsRow} aria-label="Companies in this stack">
          <span className={styles.companyPillsLabel}>Companies:</span>
          {topCompanies.map(([comp, count]) => (
            <span key={comp} className={styles.companyChip}>
              {comp} <span className={styles.companyChipCount}>({count})</span>
            </span>
          ))}
          {remainingCompanyCount > 0 && (
            <span className={styles.moreCompaniesChip}>
              +{remainingCompanyCount} more
            </span>
          )}
        </div>
      )}

      {/* Stacked 3D Card Deck (when collapsed) */}
      {!isExpanded && jobs.length > 1 && activeJob && (
        <div className={styles.deckWrapper}>
          <div className={styles.deckLayers}>
            {/* Visual offset cards behind the top card */}
            <div className={styles.layer2} aria-hidden="true" />
            <div className={styles.layer1} aria-hidden="true" />

            <div className={styles.topCardBox}>
              <ApplicationCard
                job={activeJob}
                busy={busy}
                detailed={detailId === activeJob.id}
                onDetails={() => onDetails(activeJob)}
                onApply={() => onApply(activeJob)}
                onAssistedFill={onAssistedFill ? () => onAssistedFill(activeJob) : undefined}
                onRetry={onRetry ? () => onRetry(activeJob) : undefined}
              />
            </div>
          </div>

          <div className={styles.deckControls}>
            <div className={styles.cardStepper}>
              <button
                type="button"
                className={styles.stepBtn}
                disabled={activeIndex === 0}
                onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
                aria-label="Previous card in stack"
                title="Previous card"
              >
                ◀
              </button>
              <span className={styles.stepperLabel}>
                Card {activeIndex + 1} of {jobs.length}
              </span>
              <button
                type="button"
                className={styles.stepBtn}
                disabled={activeIndex >= jobs.length - 1}
                onClick={() => setCurrentIndex((prev) => Math.min(jobs.length - 1, prev + 1))}
                aria-label="Next card in stack"
                title="Next card"
              >
                ▶
              </button>
            </div>

            <button
              type="button"
              className={styles.expandLink}
              onClick={() => setIsExpanded(true)}
            >
              Show all {jobs.length} cards →
            </button>
          </div>
        </div>
      )}

      {/* Expanded Grid (or single card) */}
      {(isExpanded || jobs.length === 1) && (
        <div className={styles.expandedGrid}>
          {jobs.map((job) => (
            <ApplicationCard
              key={job.id}
              job={job}
              busy={busy}
              detailed={detailId === job.id}
              onDetails={() => onDetails(job)}
              onApply={() => onApply(job)}
              onAssistedFill={onAssistedFill ? () => onAssistedFill(job) : undefined}
              onRetry={onRetry ? () => onRetry(job) : undefined}
            />
          ))}
        </div>
      )}
    </section>
  );
}
