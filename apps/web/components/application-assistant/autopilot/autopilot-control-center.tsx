"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  getAutopilotJobsPage,
  pauseAutopilot,
  startAutopilot,
  stopAutopilot,
} from "@/lib/application-assistant-api";
import {
  OPERATIONAL_LABELS,
  PIPELINE_STAGES,
  resolveOperationalState,
  stageIndexForStep,
  useAutopilotState,
  type AutopilotLog,
} from "@/hooks/use-autopilot-state";
import { AutopilotApplicationsView } from "./autopilot-applications-view";
import styles from "./control-center.module.css";
import { RecentSubmissions } from "./recent-submissions";
import { NightBatchCard, type NightBatchConfig } from "./night-batch-card";
import { LastUpdatePanel } from "./last-update-panel";

type SectionId = "overview" | "applications" | "review" | "diagnostics";

import type { AutopilotJobRow } from "./job-types";
export type { AutopilotJobRow } from "./job-types";

// INELIGIBLE must be listed here or the page never fetches those rows at all,
// and the Ineligible filter below silently shows nothing.
const ALL_STATUSES = ["QUEUED", "APPLYING", "SUBMITTED", "NEEDS_REVIEW", "STAGED", "FAILED", "SKIPPED", "INELIGIBLE"];

function isSameDay(iso: string | undefined, ref: Date): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return false;
  return d.toDateString() === ref.toDateString();
}

function timeOfDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** Classify a log line into a feed event kind using the message the backend already emits. */
function feedKind(log: AutopilotLog): { kind: string; glyph: string } {
  const m = (log.message || "").toLowerCase();
  if (log.level === "error" || m.includes("failed")) return { kind: "failed", glyph: "✕" };
  if (m.includes("submitted")) return { kind: "submitted", glyph: "✓" };
  if (m.includes("skip")) return { kind: "skipped", glyph: "⊘" };
  if (m.includes("review") || m.includes("staged")) return { kind: "review", glyph: "⚠" };
  if (m.includes("repair") || m.includes("heal")) return { kind: "healed", glyph: "↻" };
  return { kind: "applying", glyph: "◉" };
}

export function AutopilotControlCenter({
  initialSection = "overview",
}: {
  initialSection?: SectionId;
}) {
  const { state, loading, connectionError, refresh } = useAutopilotState();
  const [section, setSection] = useState<SectionId>(initialSection);
  const [jobs, setJobs] = useState<AutopilotJobRow[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [batchPanelOpen, setBatchPanelOpen] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);

  const loadJobs = useCallback(async () => {
    if (section !== "overview") return;
    // One paginated request across every status rather than a fan-out per
    // status — fewer round trips, and the whole view stops depending on the
    // slowest of seven parallel calls before it can show a single number.
    try {
      const merged: AutopilotJobRow[] = [];
      const seen = new Set<string>();
      let offset = 0;
      for (let page = 0; page < 10; page += 1) {
        const res = await getAutopilotJobsPage({
          status: ALL_STATUSES.join(","),
          limit: 200,
          offset,
          sortBy: "updatedAt",
          sortDir: "desc",
        });
        const batch = (res.jobs || []) as AutopilotJobRow[];
        for (const job of batch) {
          if (job?.id && !seen.has(job.id)) {
            seen.add(job.id);
            merged.push(job);
          }
        }
        if (!res.hasMore || batch.length === 0) break;
        offset += batch.length;
      }
      setJobs(merged);
    } catch {
      // Leave the previous snapshot in place rather than blanking the view on
      // a transient failure; the interval below retries.
    } finally {
      setJobsLoading(false);
    }
  }, [section]);

  useEffect(() => {
    if (section !== "overview") return;
    void loadJobs();
    const interval = setInterval(() => void loadJobs(), 15_000);
    return () => clearInterval(interval);
  }, [loadJobs, section]);

  const opState = resolveOperationalState(state, connectionError);
  const opCopy = OPERATIONAL_LABELS[opState];
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
    // A re-discovered posting that was already submitted can end up applied
    // to twice - a real duplicate submission, flagged duplicateSubmission so
    // it isn't double-counted here even though the row itself stays SUBMITTED.
    const submitted = jobs.filter((j) => j.status === "SUBMITTED" && !j.duplicateSubmission && isSameDay(j.submittedAt || j.updatedAt, now)).length;
    const skipped = jobs.filter((j) => j.status === "SKIPPED" && isSameDay(j.updatedAt, now)).length;
    const failed = jobs.filter((j) => j.status === "FAILED" && isSameDay(j.updatedAt, now)).length;
    const review = jobs.filter((j) => (j.status === "NEEDS_REVIEW" || j.status === "STAGED")).length;
    const pending = jobs.filter((j) => j.status === "QUEUED").length;
    return { submitted, skipped, failed, review, pending, evaluated: submitted + skipped + failed };
  }, [jobs]);

  // Success rate is defined explicitly: of the applications Autopilot actually
  // carried to a terminal automated outcome, how many were submitted. Skipped
  // jobs are excluded — they were filtered by choice, not failures.
  const successRate = useMemo(() => {
    const submitted = cumulative?.submitted ?? 0;
    const failed = cumulative?.failed ?? 0;
    const denom = submitted + failed;
    if (denom === 0) return null;
    return Math.round((submitted / denom) * 100);
  }, [cumulative]);

  const reviewJobs = useMemo(
    () => jobs.filter((j) => j.status === "NEEDS_REVIEW" || j.status === "STAGED"),
    [jobs],
  );

  const authJobs = useMemo(
    () =>
      jobs.filter(
        (j) => j.lastErrorType === "AUTH_REQUIRED" || j.lastErrorType === "CAPTCHA",
      ),
    [jobs],
  );

  const health = useMemo(() => {
    if (connectionError) return "offline" as const;
    if (state?.selfHealing?.status && state.selfHealing.status !== "idle") return "degraded" as const;
    if (authJobs.length > 0) return "attention" as const;
    return "healthy" as const;
  }, [connectionError, state?.selfHealing?.status, authJobs.length]);

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
      setControlError(err instanceof Error ? err.message : "Could not start Night Batch");
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

      {/* Slim status bar: what's happening now, and how to start something new.
          Night Batch itself is a subset reached from here rather than an
          always-on hero — it only renders below while live or explicitly
          opened via "Night Batch Run". */}
      {section === "overview" && (
        <>
          <section className={styles.activityDock} aria-label="Autopilot status">
            <span className={`${styles.statusDot} ${isLive ? styles.statusDotLive : ""}`} />
            <div>
              <strong>{opState === "recovering" ? "Self-healing in progress" : isLive ? "Currently running" : "Ready"}</strong>
              <small>
                {opState === "recovering"
                  ? `${state?.selfHealing?.status} · Round ${state?.selfHealing?.currentRound} of ${state?.selfHealing?.maxRounds}`
                  : isLive && liveJob
                    ? `${liveJob.company} · ${liveJob.title}`
                    : opCopy.detail}
              </small>
            </div>
            {isLive ? (
              <>
                <button className={styles.filterChip} disabled={controlBusy} onClick={() => void runControl("pause")}>Pause</button>
                <button className={styles.filterChip} disabled={controlBusy} onClick={() => void runControl("stop")}>Stop</button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className={`${styles.filterChip} ${batchPanelOpen ? styles.filterChipActive : ""}`}
                  aria-pressed={batchPanelOpen}
                  aria-controls="night-batch"
                  onClick={() => setBatchPanelOpen((value) => !value)}
                >
                  Night Batch Run
                </button>
                <button
                  type="button"
                  className={styles.filterChip}
                  disabled={controlBusy}
                  onClick={() =>
                    void handleStartNightBatch({
                      batchSize: 1,
                      minMatchScore: 60,
                      tierGuardrails: true,
                      selfHealing: true,
                    })
                  }
                >
                  Single Apply
                </button>
              </>
            )}
          </section>

          {(isLive || batchPanelOpen) && (
            <div id="night-batch" className={styles.batchRow} data-has-history={Boolean(lastActivity || (state?.run?.processedCount ?? 0) > 0)}>
              <NightBatchCard
                isLive={isLive}
                onStartBatch={handleStartNightBatch}
                onPause={() => runControl("pause")}
                onStop={() => runControl("stop")}
                busy={controlBusy}
                liveJob={liveJob}
                targetCount={state?.run?.targetProcessCount ?? 10}
                processedCount={state?.run?.processedCount ?? 0}
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
          )}

          <div className={styles.liveWorkspace} data-idle={!loading && !isLive && !(state?.recentLogs?.length)}>
            <RecentSubmissions />
          </div>
        </>
      )}
      <nav className={styles.tabs}>
        {([
          ["overview", "Overview", 0],
          ["applications", "Applications", 0],
          ["review", "Review", reviewJobs.length],
          ["diagnostics", "Diagnostics", 0],
        ] as [SectionId, string, number][]).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            aria-pressed={section === id}
            className={`${styles.tab} ${section === id ? styles.tabActive : ""}`}
          >
            {label}
            {count > 0 && <span className={styles.tabCount}>{count}</span>}
          </button>
        ))}
      </nav>

      {section === "overview" && (
        <div className={styles.overviewGrid}>
          <div className={styles.mainCol}>
            {/* ── Operational metrics ── */}
            <div className={styles.metricGrid}>
              <div className={styles.metric} data-tone="success">
                <div className={styles.metricValue}>{jobsLoading ? "—" : today.submitted}</div>
                <div className={styles.metricLabel}>Submitted today</div>
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
                <div className={styles.metricHint}>submitted ÷ (submitted + failed)</div>
              </div>
              <div className={styles.metric} data-tone="attention">
                <div className={styles.metricValue}>{jobsLoading ? "—" : reviewJobs.length}</div>
                <div className={styles.metricLabel}>Need your review</div>
              </div>
            </div>

            {/* ── Attention center ── */}
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <span className={styles.panelTitle}>Needs your attention</span>
              </div>
              {jobsLoading ? (
                <p className={styles.loadingText}>Checking…</p>
              ) : reviewJobs.length === 0 && authJobs.length === 0 ? (
                <div className={styles.allClear}>
                  <span className={styles.allClearDot}>●</span>
                  Nothing needs you right now — everything else is being handled automatically.
                </div>
              ) : (
                <div>
                  {reviewJobs.length > 0 && (
                    <div className={styles.attentionItem} data-kind="review">
                      <span className={styles.attentionIcon}>⚠</span>
                      <div className={styles.attentionBody}>
                        <div className={styles.attentionTitle}>
                          {reviewJobs.length} application{reviewJobs.length === 1 ? "" : "s"} need review
                        </div>
                        <div className={styles.attentionDetail}>
                          Autopilot wasn&apos;t confident enough to safely submit without your answer.
                        </div>
                      </div>
                      <button type="button" className={styles.attentionAction} onClick={() => setSection("applications")}>
                        Review
                      </button>
                    </div>
                  )}
                  {authJobs.length > 0 && (
                    <div className={styles.attentionItem} data-kind="auth">
                      <span className={styles.attentionIcon}>🔑</span>
                      <div className={styles.attentionBody}>
                        <div className={styles.attentionTitle}>
                          {authJobs.length} site{authJobs.length === 1 ? "" : "s"} need authentication
                        </div>
                        <div className={styles.attentionDetail}>
                          {Array.from(new Set(authJobs.map((j) => j.company).filter(Boolean))).slice(0, 4).join(", ")}
                          {" — sign in so Autopilot can continue."}
                        </div>
                      </div>
                      <button type="button" className={styles.attentionAction} onClick={() => setSection("diagnostics")}>
                        Fix
                      </button>
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>

          <div className={styles.sideCol}>
            {/* ── Today ── */}
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <span className={styles.panelTitle}>Today</span>
              </div>
              <div className={styles.panelBody} style={{ paddingTop: "0.35rem", paddingBottom: "0.35rem" }}>
                <div className={styles.todayRow}>
                  <span>Evaluated</span>
                  <strong>{jobsLoading ? "—" : today.evaluated}</strong>
                </div>
                <div className={styles.todayRow}>
                  <span>Submitted</span>
                  <strong>{jobsLoading ? "—" : today.submitted}</strong>
                </div>
                <div className={styles.todayRow}>
                  <span>Skipped</span>
                  <strong>{jobsLoading ? "—" : today.skipped}</strong>
                </div>
                <div className={styles.todayRow}>
                  <span>Queued</span>
                  <strong>{jobsLoading ? "—" : today.pending}</strong>
                </div>
              </div>
            </section>

            {/* ── System health ── */}
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <span className={styles.panelTitle}>System health</span>
                <span className={styles.healthBadge} data-health={health}>
                  <span className={styles.statusDot} style={{ background: "currentColor" }} />
                  {health === "healthy" ? "Healthy" : health === "degraded" ? "Degraded" : health === "attention" ? "Attention" : "Offline"}
                </span>
              </div>
              <div className={styles.panelBody} style={{ paddingTop: "0.35rem" }}>
                <div className={styles.healthRow}>
                  <span>Applications today</span>
                  <strong>{jobsLoading ? "—" : today.submitted}</strong>
                </div>
                <div className={styles.healthRow}>
                  <span>Success rate</span>
                  <strong>{successRate == null ? "—" : `${successRate}%`}</strong>
                </div>
                <div className={styles.healthRow}>
                  <span>Auto-recovered</span>
                  <strong>{state?.selfHealing ? state.selfHealing.patchesApplied : "—"}</strong>
                </div>
                <div className={styles.healthRow}>
                  <span>Human intervention</span>
                  <strong>{jobsLoading ? "—" : reviewJobs.length + authJobs.length}</strong>
                </div>

                {state?.selfHealing?.lastPatchSummary ? (
                  <div className={styles.recoveryBlock}>
                    <span className={styles.recoveryLabel}>Last recovery</span>
                    {state.selfHealing.lastPatchSummary}
                  </div>
                ) : null}
              </div>
            </section>

            {/* ── Activity feed ── */}
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <span className={styles.panelTitle}>Recent activity</span>
              </div>
              {!state || (state.recentLogs || []).length === 0 ? (
                <p className={styles.loadingText}>No Autopilot activity recorded yet.</p>
              ) : (
                <div className={styles.feedScroll}>
                  {[...(state.recentLogs || [])]
                    .reverse()
                    .slice(0, 60)
                    .map((log) => {
                      const { kind, glyph } = feedKind(log);
                      const company = log.metadata?.company as string | undefined;
                      return (
                        <div key={log.id} className={styles.feedItem}>
                          <span className={styles.feedTime}>{timeOfDay(log.timestamp)}</span>
                          <span className={styles.feedIcon} data-kind={kind}>{glyph}</span>
                          <span>
                            <span className={styles.feedTitle}>{company || "Autopilot"}</span>
                            <span className={styles.feedDetail}>{log.message}</span>
                          </span>
                        </div>
                      );
                    })}
                </div>
              )}
            </section>
          </div>
        </div>
      )}

      {section !== "overview" && (
        <AutopilotApplicationsView
          section={section}
          onJobsChanged={loadJobs}
        />
      )}
    </div>
  );
}
