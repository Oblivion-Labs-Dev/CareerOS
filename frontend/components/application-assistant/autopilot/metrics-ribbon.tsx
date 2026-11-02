"use client";

import React from "react";
import {
  IconAlertCircle,
  IconCheckCircle,
  IconClock,
  IconInbox,
  IconSend,
} from "./icons";
import styles from "./autopilot-ui.module.css";

interface ConcurrencyMetrics {
  activeWorkers: number;
  totalWorkers: number;
  avgJobTimeSec: number;
  throughputPerMin: number;
  lockContentionCount: number;
  selfHealingRoundsCompleted: number;
}

interface SelfHealingInfo {
  status: string;
  currentRound: number;
  maxRounds: number;
  lastPatchSummary: string;
  patchesApplied: number;
}

interface MetricsRibbonProps {
  submitted: number;
  staged: number;
  skipped: number;
  failed: number;
  queueRemaining: number;
  processedCount: number;
  concurrencyMetrics?: ConcurrencyMetrics;
  selfHealing?: SelfHealingInfo;
  onSelectCategory?: (category: "SUBMITTED" | "STAGED" | "SKIPPED" | "FAILED" | "QUEUED") => void;
}

type Category = "SUBMITTED" | "STAGED" | "SKIPPED" | "FAILED" | "QUEUED";

function Sparkline({ d }: { d: string }) {
  return (
    <div className={styles.metricSparkline}>
      <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
        <path d={d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    </div>
  );
}

function MetricCard({
  category,
  variant,
  icon,
  label,
  value,
  subvalue,
  sparkline,
  wide,
  onSelect,
}: {
  category: Category;
  variant: "success" | "warning" | "info" | "danger" | "accent";
  icon: React.ReactNode;
  label: string;
  value: number;
  subvalue: string;
  sparkline: string;
  wide?: boolean;
  onSelect?: (category: Category) => void;
}) {
  return (
    <div
      onClick={() => onSelect?.(category)}
      data-variant={variant}
      className={`${styles.metricCard} ${wide ? styles.metricCardWide : ""}`}
    >
      <div className={styles.metricHead}>
        <div className={styles.metricIconWrap}>{icon}</div>
        <span className={styles.metricLabel}>{label}</span>
      </div>
      <div className={styles.metricBody}>
        <span className={styles.metricValue}>{value}</span>
        <span className={styles.metricSubvalue}>{subvalue}</span>
      </div>
      <Sparkline d={sparkline} />
    </div>
  );
}

export function MetricsRibbon({
  submitted,
  staged,
  skipped,
  failed,
  queueRemaining,
  processedCount,
  concurrencyMetrics,
  selfHealing,
  onSelectCategory,
}: MetricsRibbonProps) {
  const baseCount = Math.max(1, processedCount);
  const successPct = Math.round((submitted / baseCount) * 100);
  const stagedPct = Math.round((staged / baseCount) * 100);
  const skipPct = Math.round((skipped / baseCount) * 100);
  const failPct = Math.round((failed / baseCount) * 100);

  return (
    <div className="space-y-4">
      <div className={styles.metricsGrid}>
        <MetricCard
          category="SUBMITTED"
          variant="success"
          icon={<IconSend className="w-4 h-4" />}
          label="Submitted"
          value={submitted}
          subvalue={`${successPct}% rate`}
          sparkline="M0 20 Q30 18 60 12 T120 4"
          onSelect={onSelectCategory}
        />
        <MetricCard
          category="STAGED"
          variant="warning"
          icon={<IconClock className="w-4 h-4" />}
          label="In Review"
          value={staged}
          subvalue={`${stagedPct}% review`}
          sparkline="M0 16 Q30 8 60 18 T120 10"
          onSelect={onSelectCategory}
        />
        <MetricCard
          category="SKIPPED"
          variant="info"
          icon={<IconInbox className="w-4 h-4" />}
          label="Skipped"
          value={skipped}
          subvalue={`${skipPct}% skipped`}
          sparkline="M0 18 Q40 14 80 16 T120 8"
          onSelect={onSelectCategory}
        />
        <MetricCard
          category="FAILED"
          variant="danger"
          icon={<IconAlertCircle className="w-4 h-4" />}
          label="Failed"
          value={failed}
          subvalue={`${failPct}% error`}
          sparkline="M0 20 Q40 20 80 16 T120 14"
          onSelect={onSelectCategory}
        />
        <MetricCard
          category="QUEUED"
          variant="accent"
          icon={<IconCheckCircle className="w-4 h-4" />}
          label="Queue"
          value={queueRemaining}
          subvalue="Active queue"
          sparkline="M0 10 Q30 16 60 8 T120 18"
          wide
          onSelect={onSelectCategory}
        />
      </div>

      {concurrencyMetrics && (
        <div className={styles.concurrencyGrid}>
          <div className={styles.concurrencyCard} data-variant="workers">
            <div className={styles.concurrencyIconWrap}>{concurrencyMetrics.activeWorkers}</div>
            <div className="min-w-0">
              <div className={styles.concurrencyLabel}>Active Workers</div>
              <div className={styles.concurrencyValue}>
                {concurrencyMetrics.activeWorkers}/{concurrencyMetrics.totalWorkers} slots
              </div>
            </div>
          </div>

          <div className={styles.concurrencyCard} data-variant="throughput">
            <div className={styles.concurrencyIconWrap}>⚡</div>
            <div className="min-w-0">
              <div className={styles.concurrencyLabel}>Throughput</div>
              <div className={styles.concurrencyValue}>
                {concurrencyMetrics.throughputPerMin.toFixed(1)} jobs/min
                <span className={styles.concurrencyValueMuted}>
                  (avg {concurrencyMetrics.avgJobTimeSec.toFixed(0)}s)
                </span>
              </div>
            </div>
          </div>

          <div className={styles.concurrencyCard} data-variant="healing">
            <div className={styles.concurrencyIconWrap}>🔧</div>
            <div className="min-w-0">
              <div className={styles.concurrencyLabel}>Self-Healing</div>
              <div className={styles.concurrencyValue}>
                {selfHealing?.status === "idle" ? (
                  <>
                    {selfHealing.patchesApplied > 0
                      ? `${selfHealing.patchesApplied} patch(es) applied`
                      : "Standby"}
                  </>
                ) : (
                  <span className="animate-pulse">
                    {selfHealing?.status}… (Round {selfHealing?.currentRound}/{selfHealing?.maxRounds})
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
