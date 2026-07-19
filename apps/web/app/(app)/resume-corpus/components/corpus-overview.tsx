"use client";

import { MetricCard, StatePanel } from "@arsenal/ui";
import type { KeyboardEvent } from "react";
import type { CorpusProfile, CorpusRecord, CorpusSummary } from "../corpus-model";
import type { CorpusView } from "../corpus-navigation";
import { dimensionStatus, GAP_CATEGORIES, rankPriorityItems, summarizeBulletReadiness } from "../corpus-quality";
import styles from "../resume-corpus.module.css";

interface CorpusOverviewProps {
  profile: CorpusProfile;
  records: CorpusRecord[];
  summary: CorpusSummary;
  previewMode: boolean;
  onNavigate: (view: CorpusView) => void;
  onSelectRecord: (record: CorpusRecord, sectionId?: string) => void;
  onCreate: () => void;
}

interface DashboardMetric {
  label: string;
  value: string | number;
  description: string;
  detail: string;
  tone: "default" | "accent" | "success" | "danger";
  detailTone: "neutral" | "accent" | "success" | "danger";
  action: () => void;
}

function formatDate(value?: string): string {
  if (!value) return "No updates";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "Date unavailable";
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(timestamp));
}

function scoreTone(score: number): "success" | "accent" | "danger" {
  if (score >= 75) return "success";
  if (score >= 45) return "accent";
  return "danger";
}

function activateWithKeyboard(event: KeyboardEvent<HTMLElement>, action: () => void): void {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  action();
}

export function CorpusOverview({
  profile,
  records,
  summary,
  previewMode,
  onNavigate,
  onSelectRecord,
  onCreate,
}: CorpusOverviewProps) {
  const quality = records.map((record) => ({ record, summary: summarizeBulletReadiness(record) }));
  const completion = quality.length === 0
    ? 0
    : Math.round(quality.reduce((total, item) => total + item.summary.completionPercent, 0) / quality.length);
  const interviewReady = quality.filter((item) => dimensionStatus(item.record, "interview-readiness") === "interview-ready").length;
  const missingInformation = quality.reduce((total, item) => total + item.summary.missingCount, 0);
  const allMetrics = records.flatMap((record) => record.metrics);
  const verifiedMetrics = allMetrics.filter((metric) => metric.verification === "verified").length;
  const mostRecent = [...records]
    .sort((left, right) => Date.parse(right.updatedAt ?? "") - Date.parse(left.updatedAt ?? ""))[0];
  const topPriority = rankPriorityItems(records, 1)[0];
  const priorityRecord = topPriority ? records.find((record) => record.id === topPriority.recordId) : undefined;
  const prioritySection = topPriority?.gapCategory
    ? GAP_CATEGORIES.find((category) => category.id === topPriority.gapCategory)?.sectionId
    : topPriority?.questionId
      ? "interview"
      : undefined;

  const metrics: DashboardMetric[] = [
    {
      label: "Total accomplishments",
      value: records.length,
      description: "Canonical engineering stories in your corpus.",
      detail: "Open accomplishments",
      tone: "default",
      detailTone: "neutral",
      action: () => onNavigate("accomplishments"),
    },
    {
      label: "Completion",
      value: completion + "%",
      description: "Average completion across the canonical quality model.",
      detail: records.length + (records.length === 1 ? " story" : " stories"),
      tone: scoreTone(completion),
      detailTone: "neutral",
      action: () => onNavigate("accomplishments"),
    },
    {
      label: "Interview ready",
      value: interviewReady,
      description: "Accomplishments with complete, practiced interview coverage.",
      detail: interviewReady === records.length && records.length > 0 ? "All stories ready" : "Open interview prep",
      tone: interviewReady > 0 ? "success" : "default",
      detailTone: interviewReady > 0 ? "success" : "neutral",
      action: () => onNavigate("interview"),
    },
    {
      label: "Missing information",
      value: missingInformation,
      description: "Required details still absent across all accomplishments.",
      detail: missingInformation === 0 ? "No known gaps" : "Needs attention",
      tone: missingInformation === 0 ? "success" : "danger",
      detailTone: missingInformation === 0 ? "success" : "danger",
      action: () => onNavigate("accomplishments"),
    },
    {
      label: "Evidence coverage",
      value: summary.evidenceCoverage + "%",
      description: "Accomplishments supported by at least one artifact.",
      detail: "Open evidence",
      tone: scoreTone(summary.evidenceCoverage),
      detailTone: "neutral",
      action: () => onNavigate("evidence"),
    },
    {
      label: "Verified metrics",
      value: verifiedMetrics,
      description: "Metrics with a confirmed source or supporting evidence.",
      detail: allMetrics.length + " total " + (allMetrics.length === 1 ? "metric" : "metrics"),
      tone: verifiedMetrics > 0 ? "success" : "default",
      detailTone: verifiedMetrics > 0 ? "success" : "neutral",
      action: () => onNavigate("metrics"),
    },
    {
      label: "Recent updates",
      value: formatDate(mostRecent?.updatedAt),
      description: mostRecent ? mostRecent.title : "No accomplishments have been updated yet.",
      detail: mostRecent?.company || "Start with one story",
      tone: "default",
      detailTone: "neutral",
      action: () => mostRecent ? onSelectRecord(mostRecent) : onCreate(),
    },
    {
      label: "Top priority",
      value: priorityRecord?.title || "All clear",
      description: topPriority?.title || "No high-value missing information is currently open.",
      detail: topPriority ? topPriority.resumeImpact + " resume impact" : "Keep the corpus current",
      tone: topPriority ? "accent" : "success",
      detailTone: topPriority ? "accent" : "success",
      action: () => priorityRecord ? onSelectRecord(priorityRecord, prioritySection) : onNavigate("accomplishments"),
    },
  ];

  return (
    <div className={styles.viewStack}>
      <div className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>{previewMode ? "Sample corpus" : "Phase 1"}</div>
          <h1>Resume Corpus</h1>
          <p>
            {profile.fullName}&apos;s source of truth for engineering accomplishments, evidence, and interview-ready stories.
          </p>
        </div>
        <button type="button" className={styles.primaryButton} onClick={onCreate}>+ New accomplishment</button>
      </div>

      {records.length === 0 ? (
        <StatePanel
          kind="empty"
          title="Capture your first engineering accomplishment"
          description="Start with the problem, what you owned, one engineering decision, a defensible result, and any evidence you can safely reference."
          action={<button type="button" className={styles.primaryButton} onClick={onCreate}>Create accomplishment</button>}
        />
      ) : (
        <section aria-label="Resume corpus overview">
          <div className={styles.phase1OverviewMetrics}>
            {metrics.map((metric) => (
              <MetricCard
                key={metric.label}
                label={metric.label}
                value={metric.value}
                description={metric.description}
                trend={{ label: metric.detail, direction: "neutral", tone: metric.detailTone }}
                tone={metric.tone}
                className={[styles.metricCard, styles.phase1OverviewMetric].join(" ")}
                role="button"
                tabIndex={0}
                aria-description={metric.description + " Activate to open the related workspace."}
                onClick={metric.action}
                onKeyDown={(event) => activateWithKeyboard(event, metric.action)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}


