"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AutopilotRefusedError,
  fetchAutopilotReadiness,
  getAutopilotJobsPage,
  getAutopilotStats,
  pauseAutopilot,
  startAutopilot,
  stopAutopilot,
  type AutopilotReadiness,
} from "@/lib/application-assistant-api";
import {
  PIPELINE_STAGES,
  resolveOperationalState,
  stageIndexForStep,
  useAutopilotState,
} from "@/hooks/use-autopilot-state";
import { AutopilotApplicationsView } from "./autopilot-applications-view";
import styles from "./control-center.module.css";
import { NightBatchCard, type NightBatchConfig } from "./night-batch-card";
import { LastUpdatePanel } from "./last-update-panel";

// Legacy `?tab=` values this page still accepts (see CONTROL_CENTER_TABS in
// the route). Overview and Applications are no longer separate sections —
// both always render together — so this is only consulted once, on mount,
// to redirect a stale "diagnostics" link to the page that actually owns that
// content now.
type SectionId = "overview" | "applications" | "review" | "diagnostics";

import type { AutopilotJobRow } from "./job-types";
export type { AutopilotJobRow } from "./job-types";

// INELIGIBLE and MANUAL_REVIEW must be listed here
const ALL_STATUSES = [
  "QUEUED",
  "APPLYING",
  "SUBMITTED",
  "NEEDS_REVIEW",
  "STAGED",
  "MANUAL_REVIEW",
  "FAILED",
  "SKIPPED",
  "INELIGIBLE",
];

function isSameDay(iso: string | undefined, ref: Date): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return d.toDateString() === ref.toDateString();
}

export function AutopilotControlCenter({
  initialSection = "overview",
}: {
  initialSection?: SectionId;
}) {
  const router = useRouter();
  const { state, loading, connectionError, refresh } = useAutopilotState();
  const [jobs, setJobs] = useState<AutopilotJobRow[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  // True per-status totals across every job, not just the 100 most recently
  // touched ones `jobs` holds — "Need your review" read off that capped,
  // recency-sorted sample showed 7 while the real In-Review + Manual-Review
  // total was over 2,000, because almost none of the top 100 most-recently-
  // updated rows (across all 9 statuses, during an active batch run) happened
  // to be review rows at that instant.
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({});
  // Submitted-today/24h come from the same cheap stats aggregate rather than
  // a dedicated fetch of up to 500 full SUBMITTED job rows — that fetch was
  // adding real weight to every page load just to count two numbers.
  const [submittedToday, setSubmittedToday] = useState(0);
  const [submitted24h, setSubmitted24h] = useState(0);
  const [statsLoading, setStatsLoading] = useState(true);
  const [controlBusy, setControlBusy] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);
  // Pre-flight readiness, fetched alongside the rest of the dashboard so the
  // card can show what is missing before Start is pressed rather than after a
  // refusal. A failure here is never fatal: the gate still refuses server-side.
  const [readiness, setReadiness] = useState<AutopilotReadiness | null>(null);

  // A stale "?tab=diagnostics" link is the one legacy case that actually
  // points somewhere else now — Diagnostics moved to its own page rather
  // than rendering inline here.
  useEffect(() => {
    if (initialSection === "diagnostics") router.replace("/diagnostic");
  }, [initialSection, router]);

  // Each call resolves independently — the metric tiles that only need
  // `jobs` (or only need `statusCounts`) render as soon as their own fetch
  // lands, instead of every tile waiting on whichever of the two is slowest.
  const loadJobs = useCallback(() => {
    void getAutopilotJobsPage({
      status: ALL_STATUSES.join(","),
      limit: 100,
      sortBy: "updatedAt",
      sortDir: "desc",
    })
      .then((res) => setJobs((res.jobs || []) as AutopilotJobRow[]))
      .catch(() => {
        // Leave previous snapshot in place on transient error
      })
      .finally(() => setJobsLoading(false));

    void getAutopilotStats()
      .then((res) => {
        if (res.success) {
          setStatusCounts(res.statusCounts || {});
          setSubmittedToday(res.submittedToday ?? 0);
          setSubmitted24h(res.submitted24h ?? 0);
        }
      })
      .catch(() => {
        // Leave previous snapshot in place on transient error
      })
      .finally(() => setStatsLoading(false));
  }, []);

  useEffect(() => {
    void loadJobs();
    const interval = setInterval(() => void loadJobs(), 15_000);
    return () => clearInterval(interval);
  }, [loadJobs]);

  // Readiness changes only when the profile or the review queue does, so it is
  // refreshed on mount and after a run rather than on the 15s job poll.
  const loadReadiness = useCallback(() => {
    fetchAutopilotReadiness()
      .then(setReadiness)
      .catch(() => {
        // Advisory only — the gate still refuses server-side if this is stale.
      });
  }, []);

  useEffect(() => loadReadiness(), [loadReadiness]);

  const opState = resolveOperationalState(state, connectionError);
  const isLive = opState === "running" || opState === "recovering";

  const cumulative = state?.cumulative ?? null;

  // Real live job: the worker actually holding one, else the run's activeJob.
  const liveWorker = (state?.workers || []).find((w) => w.currentJob);
  const liveJob = liveWorker?.currentJob
    ? {
        company: liveWorker.currentJob.company,
        title: liveWorker.currentJob.title,
        step: liveWorker.currentStep,
        stage: undefined,
        model: state?.batchConfig?.aiModel || "Qwen3:4b-instruct",
        durationMs: undefined,
        message: undefined,
      }
    : state?.activeJob
      ? {
          company: String(state.activeJob.company ?? ""),
          title: String(state.activeJob.title ?? ""),
          step: String(state.activeJob.currentStep ?? ""),
          stage: state.activeJob.stage as string | undefined,
          model: (state.activeJob.model as string | undefined) || state?.batchConfig?.aiModel || "Qwen3:4b-instruct",
          durationMs: state.activeJob.durationMs as number | undefined,
          message: state.activeJob.message as string | undefined,
        }
      : null;

  // Stage position comes from the job record's checkpoint code, never from the
  // worker's `currentStep`. The worker reports a human sentence for the live
  // caption ("Clicking 'button:has-text(\"Apply\")' to expose application
  // form..."), which matches no entry in PIPELINE_STAGES, so deriving the stage
  // from it pinned the pipeline at -1 and every stage rendered as pending for
  // the whole run. The job row carries the real code (FORM_DISCOVERED,
  // QUESTIONS_COMPLETED, ...), which is what the stage list is keyed on.
  const activeStageIndex = stageIndexForStep(
    (state?.activeJob?.currentStep as string | undefined) || liveJob?.step,
  );

  const today = useMemo(() => {
    const now = new Date();
    const skipped = jobs.filter((j) => j.status === "SKIPPED" && isSameDay(j.updatedAt, now)).length;
    const failed = jobs.filter((j) => j.status === "FAILED" && isSameDay(j.updatedAt, now)).length;
    const review = jobs.filter((j) => (j.status === "NEEDS_REVIEW" || j.status === "STAGED")).length;
    const pending = jobs.filter((j) => j.status === "QUEUED").length;
    return {
      submitted: submittedToday,
      submitted24h,
      skipped,
      failed,
      review,
      pending,
      evaluated: submittedToday + skipped + failed,
    };
  }, [jobs, submittedToday, submitted24h]);

  // Share of every real attempt (submitted + manual review + in review +
  // failed) that ended in a submission. cumulative.staged covers both STAGED
  // and NEEDS_REVIEW. Skipped (filtered by choice) and ineligible (board
  // can't be automated at all) were never real attempts, so they stay out of
  // this entirely.
  const successRate = useMemo(() => {
    const submitted = cumulative?.submitted ?? 0;
    const staged = cumulative?.staged ?? 0;
    const failed = cumulative?.failed ?? 0;
    const denom = submitted + staged + failed;
    if (denom === 0) return null;
    return Math.round((submitted / denom) * 100);
  }, [cumulative]);

  // In Review (NEEDS_REVIEW + STAGED) + Manual Review — the true system-wide
  // total, not a count derived from the capped recent-jobs sample.
  const needsReviewCount = (statusCounts.NEEDS_REVIEW || 0) + (statusCounts.STAGED || 0) + (statusCounts.MANUAL_REVIEW || 0);

  // Pause/stop only. Starting a run goes through the Night Batch card, which is
  // the single place a batch is configured — there is deliberately no second
  // start path with its own hard-coded batch size and match floor.
  const runControl = async (action: "pause" | "stop") => {
    setControlBusy(true);
    setControlError(null);
    try {
      if (action === "pause") await pauseAutopilot();
      else await stopAutopilot();
      await refresh();
    } catch (err) {
      setControlError(err instanceof Error ? err.message : `Could not ${action} Autopilot`);
    } finally {
      setControlBusy(false);
    }
  };

  const handleStartNightBatch = async (config: NightBatchConfig) => {
    setControlBusy(true);
    setControlError(null);
    try {
      // Both keys are sent because the runner accepts either; `minMatchScore`
      // is the one that matters most — it is the bar a tailored resume has to
      // clear before an application is actually sent to an employer.
      await startAutopilot({
        targetProcessCount: config.batchSize,
        batchSize: config.batchSize,
        concurrency: 1,
        minMatchScore: config.minMatchScore,
        tierGuardrails: config.tierGuardrails,
        selfHealing: config.selfHealing,
      });
      await refresh();
      void loadJobs();
    } catch (err) {
      // A refusal carries the missing answers with it. Put them into the card's
      // readiness panel rather than flattening them to one sentence, so the
      // user gets the same actionable list either way.
      if (err instanceof AutopilotRefusedError) {
        if (err.readiness) {
          setReadiness((previous) =>
            previous
              ? { ...previous, profile: err.readiness! }
              : {
                  success: false,
                  profile: err.readiness!,
                  questions: { groups: [], questionCount: 0, blockedJobCount: 0, singleAnswerJobCount: 0, headline: "" },
                },
          );
        }
        setControlError(err.message);
      } else {
        setControlError(err instanceof Error ? err.message : "Could not start Night Batch");
      }
    } finally {
      setControlBusy(false);
    }
  };

  // The most recently touched application, whatever moved it: a batch
  // submission, a single Apply, a stage to review, a failure. QUEUED rows are
  // excluded because being queued is not something happening to an application,
  // and a bulk requeue would otherwise make 50 rows look like the latest news.
  const lastActivity = useMemo(() => {
    const touched = jobs
      .filter((job) => job.status && job.status !== "QUEUED" && job.updatedAt)
      .sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
    const latest = touched[0];
    if (!latest) return null;
    return {
      company: latest.company,
      title: latest.title,
      status: latest.status,
      updatedAt: latest.updatedAt,
      reason:
        latest.status === "SUBMITTED"
          ? ""
          : (latest.skipReason || latest.lastError || latest.ineligibilityDetail || "")
              .split(String.fromCharCode(10))[0].trim(),
    };
  }, [jobs]);

  // Scores of everything still queued — the card draws the match floor against
  // this so the floor's reach is visible before the run, not after it.
  const queueScores = useMemo(
    () => jobs.filter((j) => j.status === "QUEUED").map((j) => Number(j.matchScore ?? 0)),
    [jobs],
  );

  return (
    <div className={styles.page}>
      <h1 className={styles.accessibleTitle}>Autopilot</h1>

      {controlError && <div className={styles.empty}>{controlError}</div>}

      {/* Overview is always visible up top now, not a tab you navigate away
          from — Night Batch's own header shows running/ready state and
          carries its own Start (idle) and Pause/Stop (live) buttons, so it
          renders unconditionally rather than behind a section switch. */}
      <div className={styles.batchRow} data-has-history={Boolean(lastActivity || (state?.run?.processedCount ?? 0) > 0)}>
        <NightBatchCard
          isLive={isLive}
          readiness={readiness}
          onStartBatch={handleStartNightBatch}
          onPause={() => runControl("pause")}
          onStop={() => runControl("stop")}
          busy={controlBusy}
          liveJob={liveJob}
          targetCount={state?.run?.targetProcessCount ?? 10}
          processedCount={state?.run?.processedCount ?? 0}
          resumeCount={state?.run?.resumeCount ?? 1}
          submittedCount={state?.run?.submittedCount ?? 0}
          stagedCount={state?.run?.stagedCount ?? 0}
          queueScores={queueScores}
          queueLoading={jobsLoading}
          liveConfig={state?.batchConfig ?? null}
          stageIndex={activeStageIndex}
          logs={state?.recentLogs ?? []}
          healing={state?.selfHealing ?? null}
        />
        {(lastActivity || (state?.run?.processedCount ?? 0) > 0) && <LastUpdatePanel
          lastActivity={lastActivity}
          lastRun={state?.run ?? null}
          isLive={isLive}
        />}
      </div>
      <div className={styles.overviewGrid}>
          <div className={styles.mainCol}>
            {/* ── Operational metrics ── */}
            <div className={styles.metricGrid}>
              <div className={styles.metric} data-tone="success">
                <div className={styles.metricValue}>{statsLoading ? "—" : today.submitted}</div>
                <div className={styles.metricLabel}>Submitted today</div>
                {today.submitted24h > today.submitted && (
                  <div className={styles.metricHint}>{today.submitted24h} in last 24h</div>
                )}
              </div>
              <div className={styles.metric} data-tone="info">
                <div className={styles.metricValue}>{cumulative ? cumulative.submitted : "—"}</div>
                <div className={styles.metricLabel}>Total submitted</div>
              </div>
              <div className={styles.metric} data-tone="active">
                <div className={styles.metricValue}>
                  {successRate == null ? <span className={styles.unknownValue}>—</span> : `${successRate}%`}
                </div>
                <div className={styles.metricLabel}>Success rate</div>
                <div className={styles.metricHint}>submitted ÷ (submitted + review + failed)</div>
              </div>
              <div className={styles.metric} data-tone="attention">
                <div className={styles.metricValue}>{statsLoading ? "—" : needsReviewCount}</div>
                <div className={styles.metricLabel}>Need your review</div>
              </div>
            </div>
          </div>

      </div>

      <div id="application-workspace">
        <AutopilotApplicationsView
          onJobsChanged={loadJobs}
          allJobs={jobs}
          questionGroups={readiness?.questions?.groups ?? []}
          onAnswered={() => {
            // An answer can requeue applications, so both the readiness list
            // and the job counts are stale the moment it lands.
            loadReadiness();
            void loadJobs();
          }}
        />
      </div>
    </div>
  );
}
