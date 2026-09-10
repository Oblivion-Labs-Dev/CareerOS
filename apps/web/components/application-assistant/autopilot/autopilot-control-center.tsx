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
import { WorkspaceScene } from "@/components/ui/workspace-scene";

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
  const [activityExpanded, setActivityExpanded] = useState(false);
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
    ? { company: liveWorker.currentJob.company, title: liveWorker.currentJob.title, step: liveWorker.currentStep }
    : state?.activeJob
      ? {
          company: String(state.activeJob.company ?? ""),
          title: String(state.activeJob.title ?? ""),
          step: String(state.activeJob.currentStep ?? ""),
        }
      : null;

  const activeStageIndex = stageIndexForStep(liveJob?.step);

  const today = useMemo(() => {
    const now = new Date();
    const submitted = jobs.filter((j) => j.status === "SUBMITTED" && isSameDay(j.submittedAt || j.updatedAt, now)).length;
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

  const runControl = async (action: "start" | "pause" | "stop") => {
    setControlBusy(true);
    setControlError(null);
    try {
      if (action === "start") await startAutopilot({ targetProcessCount: 10, concurrency: 1 });
      else if (action === "pause") await pauseAutopilot();
      else await stopAutopilot();
      await refresh();
    } catch (err) {
      setControlError(err instanceof Error ? err.message : `Could not ${action} Autopilot`);
    } finally {
      setControlBusy(false);
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.liveHeader}>
        <h1 className={styles.title}>Autopilot</h1>
        <div className={styles.headerRight}>
          <div className={styles.statusPill} data-state={opState}>
            <span className={`${styles.statusDot} ${isLive ? styles.statusDotLive : ""}`} />
            <span className={styles.statusText}>
              <span className={styles.statusLabel}>{opCopy.label}</span>
              <span className={styles.statusDetail}>{opCopy.detail}</span>
            </span>
          </div>

          {isLive ? (
            <>
              <button type="button" className={styles.filterChip} disabled={controlBusy} onClick={() => void runControl("pause")}>
                Pause
              </button>
              <button type="button" className={styles.filterChip} disabled={controlBusy} onClick={() => void runControl("stop")}>
                Stop
              </button>
            </>
          ) : (
            <button
              type="button"
              className={`${styles.filterChip} ${styles.filterChipActive}`}
              disabled={controlBusy || connectionError}
              onClick={() => void runControl("start")}
            >
              {controlBusy ? "Starting…" : "Start run"}
            </button>
          )}
        </div>
      </header>

      {controlError && <div className={styles.empty}>{controlError}</div>}

      <section className={styles.activityDock} aria-label="Live activity dock">
        <span className={`${styles.statusDot} ${isLive ? styles.statusDotLive : ""}`} />
        <div><strong>{opState === "recovering" ? "Self-healing in progress" : liveJob ? `${liveJob.company} · ${liveJob.title}` : opCopy.label}</strong><small>{opState === "recovering" ? `${state?.selfHealing?.status} · Round ${state?.selfHealing?.currentRound} of ${state?.selfHealing?.maxRounds}` : liveJob?.step || opCopy.detail}</small></div>
        <button className={styles.filterChip} aria-expanded={activityExpanded} aria-controls="expanded-activity" onClick={() => setActivityExpanded(value => !value)}>{activityExpanded ? "Collapse activity" : "Expand activity"}</button>
      </section>
      <div id="expanded-activity" hidden={!activityExpanded}>
      <div className={styles.liveWorkspace}>
            {/* ── Live activity ── */}
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <span className={styles.panelTitle}>Live Autopilot Activity</span>
                {isLive && (
                  <span className={styles.liveTag}>
                    <span className={`${styles.statusDot} ${styles.statusDotLive}`} style={{ background: "var(--success)" }} />
                    Live
                  </span>
                )}
              </div>
              <div className={styles.panelBody}>
                {loading ? (
                  <p className={styles.loadingText}>Loading Autopilot state…</p>
                 ) : opState === "recovering" ? (
                  <div className={styles.healingActivity} role="status">
                    <span className={styles.healingGlyph} aria-hidden="true">↻</span>
                    <div><strong>Self-healing in progress</strong><p>{state?.selfHealing?.status || "Recovering"} · Round {state?.selfHealing?.currentRound ?? "—"} of {state?.selfHealing?.maxRounds ?? "—"}</p><p>{state?.selfHealing?.lastPatchSummary || "Inspecting the automation issue before retrying."}</p>{state?.selfHealing?.lastError && <p>{state.selfHealing.lastError}</p>}</div>
                  </div>
                ) : liveJob ? (
                  <>
                    <div className={styles.liveJobCompany}>Applying to {liveJob.company || "Unknown company"}</div>
                    <div className={styles.liveJobRole}>{liveJob.title || "Unknown role"}</div>

                    {liveJob.step && (
                      <div className={styles.liveOperation}>
                        <span className={styles.liveOperationLabel}>Current operation</span>
                        {liveJob.step}
                      </div>
                    )}

                    <div className={styles.pipeline}>
                      {PIPELINE_STAGES.map((stage, i) => {
                        const cls =
                          activeStageIndex < 0
                            ? ""
                            : i < activeStageIndex
                              ? styles.stageDone
                              : i === activeStageIndex
                                ? styles.stageActive
                                : "";
                        const glyph = activeStageIndex >= 0 && i < activeStageIndex ? "✓" : i === activeStageIndex ? "◉" : "○";
                        return (
                          <React.Fragment key={stage.id}>
                            <div className={`${styles.stage} ${cls}`}>
                              <span className={styles.stageMarker}>{glyph}</span>
                              <span className={styles.stageLabel}>{stage.label}</span>
                            </div>
                            {i < PIPELINE_STAGES.length - 1 && (
                              <span
                                className={`${styles.stageConnector} ${
                                  activeStageIndex >= 0 && i < activeStageIndex ? styles.stageConnectorDone : ""
                                }`}
                              />
                            )}
                          </React.Fragment>
                        );
                      })}
                    </div>
                  </>
                ) : (
                  <div className={styles.idleState}>
                    <WorkspaceScene kind="discover" compact />
                    <div className={styles.idleCopy}>
                    <strong>{opState === "paused" ? "A moment to regroup." : opState === "error" ? "Let’s reconnect." : "Ready when you are."}</strong>
                    <p>
                    {opState === "paused"
                      ? "Autopilot is paused."
                      : opState === "error"
                        ? "Can't reach the Autopilot service."
                        : state && state.queueSize > 0
                          ? `Idle — ${state.queueSize} job${state.queueSize === 1 ? "" : "s"} queued and ready to run.`
                          : "Your next opportunity starts with a search."}
                    </p>
                    <div className={styles.journey} aria-hidden="true"><span>Discover</span><i /><span>Prepare</span><i /><span>Apply</span></div>
                    </div>
                  </div>
                )}
              </div>
              <div className={styles.liveLogTrail} aria-label="Recent Autopilot activity">
                {(state?.recentLogs || []).slice(-3).reverse().map(log => <div key={log.id}><time>{timeOfDay(log.timestamp)}</time><span>{log.message}</span></div>)}
              </div>
            </section>

        <RecentSubmissions />
      </div>
      </div>
      <nav className={styles.tabs}>
        {([
          ["overview", "Overview", 0],
          ["applications", "Applications", 0],
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
