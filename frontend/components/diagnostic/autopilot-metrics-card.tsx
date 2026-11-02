"use client";

import React from "react";
import styles from "./diagnostic.module.css";
import type { AutopilotMetricsData } from "@/lib/diagnostic-api";

interface AutopilotMetricsCardProps {
  metrics: AutopilotMetricsData | null;
  period: "1h" | "24h" | "7d";
  onPeriodChange: (p: "1h" | "24h" | "7d") => void;
  loading?: boolean;
}

export function AutopilotMetricsCard({
  metrics,
  period,
  onPeriodChange,
  loading = false,
}: AutopilotMetricsCardProps) {
  return (
    <section className={styles.sectionCard} aria-label="Autopilot Metrics">
      <div className={styles.cardHeader}>
        <div className={styles.headerLeft}>
          <h2 className={styles.cardTitle}>Autopilot Metrics</h2>
          <span className={styles.subtext}>Application pipeline throughput, durations, and conversion</span>
        </div>
        <div className={styles.periodSelector} role="radiogroup" aria-label="Metrics time period">
          {(["1h", "24h", "7d"] as const).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={period === p}
              onClick={() => onPeriodChange(p)}
              className={`${styles.periodButton} ${period === p ? styles.periodActive : ""}`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.metricTilesGrid}>
        <div className={styles.metricTile}>
          <span className={styles.metricLabel}>Jobs Discovered</span>
          <span className={styles.metricNumber}>{metrics ? metrics.jobsDiscovered : "—"}</span>
          <span className={styles.metricHint}>Indexed postings</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricLabel}>Jobs Prepared</span>
          <span className={styles.metricNumber}>{metrics ? metrics.jobsPrepared : "—"}</span>
          <span className={styles.metricHint}>Resumes tailored</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricLabel}>Applications Attempted</span>
          <span className={styles.metricNumber}>{metrics ? metrics.applicationsAttempted : "—"}</span>
          <span className={styles.metricHint}>Forms opened</span>
        </div>
        <div className={styles.metricTile} data-tone="success">
          <span className={styles.metricLabel}>Successful Submissions</span>
          <span className={styles.metricNumber}>{metrics ? metrics.successfulSubmissions : "—"}</span>
          <span className={styles.metricHint}>Verified submissions</span>
        </div>
        <div className={styles.metricTile} data-tone="accent">
          <span className={styles.metricLabel}>Submission Success %</span>
          <span className={styles.metricNumber}>{metrics ? `${metrics.submissionSuccessPct}%` : "—"}</span>
          <span className={styles.metricHint}>Of attempted forms</span>
        </div>
        <div className={styles.metricTile} data-tone="warning">
          <span className={styles.metricLabel}>Staged for Review</span>
          <span className={styles.metricNumber}>{metrics ? metrics.stagedForReview : "—"}</span>
          <span className={styles.metricHint}>Needs human check</span>
        </div>
        <div className={styles.metricTile} data-tone="danger">
          <span className={styles.metricLabel}>Failures</span>
          <span className={styles.metricNumber}>{metrics ? metrics.failures : "—"}</span>
          <span className={styles.metricHint}>Terminal errors</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricLabel}>Avg App Duration</span>
          <span className={styles.metricNumber}>{metrics?.avgApplicationDurationSec != null ? `${metrics.avgApplicationDurationSec}s` : "—"}</span>
          <span className={styles.metricHint}>Recorded checkpoint span</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricLabel}>Avg Tailoring Time</span>
          <span className={styles.metricNumber}>{metrics?.avgResumeTailoringDurationSec != null ? `${metrics.avgResumeTailoringDurationSec}s` : "—"}</span>
          <span className={styles.metricHint}>No timing recorded when blank</span>
        </div>
        <div className={styles.metricTile}>
          <span className={styles.metricLabel}>Model Fallbacks</span>
          <span className={styles.metricNumber}>{metrics ? metrics.modelFallbackCount : "—"}</span>
          <span className={styles.metricHint}>Cloud / gate fallbacks</span>
        </div>
      </div>
    </section>
  );
}
