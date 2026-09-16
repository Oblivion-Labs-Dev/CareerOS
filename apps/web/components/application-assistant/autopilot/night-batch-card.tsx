"use client";

import React, { useState } from "react";
import styles from "./night-batch-card.module.css";
import { PIPELINE_STAGES, type AutopilotLog } from "@/hooks/use-autopilot-state";

export interface NightBatchConfig {
  batchSize: number;
  minMatchScore: number;
  tierGuardrails: boolean;
  selfHealing: boolean;
}

interface NightBatchCardProps {
  isLive: boolean;
  onStartBatch: (config: NightBatchConfig) => Promise<void>;
  onPause?: () => Promise<void>;
  onStop?: () => Promise<void>;
  busy?: boolean;
  liveJob?: { company: string; title: string; step?: string } | null;
  targetCount?: number;
  processedCount?: number;
  /** How many times this run has been resumed (starting at 1). The run's
   *  own targetProcessCount ratchets upward on every resume and stops
   *  meaning "batch size" after the first one, so it is not shown directly
   *  - this is the honest counter for what the user is actually seeing. */
  resumeCount?: number;
  submittedCount?: number;
  stagedCount?: number;
  /** Match scores of everything currently QUEUED, so the floor can be set
   *  against the real distribution rather than guessed at. */
  queueScores?: number[];
  /** True while that list is still being fetched. Without it an empty
   *  queueScores is indistinguishable from a genuinely empty queue, and the
   *  card claimed "queue is empty" over a queue of 369 jobs. */
  queueLoading?: boolean;
  /** What the runner reports it is actually using, so a live batch shows the
   *  configuration in force rather than whatever this card last sent. */
  liveConfig?: {
    minMatchScore: number;
    aiModel: string;
    tierGuardrails: boolean;
    selfHealing: boolean;
  } | null;
  /** Index into PIPELINE_STAGES for the step the live job is on, or -1. */
  stageIndex?: number;
  /** The runner's streaming activity log, newest last. */
  logs?: AutopilotLog[];
  /** Self-healing state, so a recovery round is visible rather than looking
   *  like the batch has stalled. */
  healing?: { status: string; currentRound: number; maxRounds: number; lastPatchSummary?: string } | null;
}

// 1 is deliberately offered: trying a single application is how you check a
// fix without committing a whole batch to it.
const BATCH_SIZE_PRESETS = [1, 10, 50, 100];
// Coarse, honest steps. A slider invited fiddling with a number whose
// effect is only visible in the reach line below it.
const MATCH_FLOORS = [50, 60, 70, 80, 90];


export function NightBatchCard({
  isLive,
  onStartBatch,
  onPause,
  onStop,
  busy = false,
  liveJob,
  targetCount = 10,
  processedCount = 0,
  resumeCount = 1,
  submittedCount = 0,
  stagedCount = 0,
  queueScores = [],
  queueLoading = false,
  liveConfig = null,
  stageIndex = -1,
  logs = [],
  healing = null,
}: NightBatchCardProps) {
  const [batchSize, setBatchSize] = useState<number>(10);

  const [minMatchScore, setMinMatchScore] = useState<number>(60);
  const [tierGuardrails, setTierGuardrails] = useState<boolean>(true);
  const [selfHealing, setSelfHealing] = useState<boolean>(true);

  const finalSize = batchSize;

  const handleStart = () => {
    void onStartBatch({
      batchSize: finalSize,
      minMatchScore,
      tierGuardrails,
      selfHealing,
    });
  };

  // The floor is the one setting most likely to make a batch quietly do
  // nothing, so its consequence belongs next to the dial rather than in the
  // logs afterwards: how much of the queue it actually reaches, drawn against
  // the real score distribution.
  const eligibleCount = React.useMemo(
    () => queueScores.filter((score) => score >= minMatchScore).length,
    [queueScores, minMatchScore],
  );


  const shortfall = queueScores.length > 0 && eligibleCount < finalSize;

  // Each floor carries the number of queued jobs it reaches, so the trade-off
  // is visible while choosing rather than only after the choice is made.
  const floorCounts = React.useMemo(() => {
    const counts = new Map<number, number>();
    for (const floor of MATCH_FLOORS) {
      counts.set(floor, queueScores.filter((score) => score >= floor).length);
    }
    return counts;
  }, [queueScores]);

  const progressPercent = targetCount > 0 ? Math.min(100, Math.round((processedCount / targetCount) * 100)) : 0;

  return (
    <section className={styles.card} aria-label="Night Batch Center">
      {/* Sky atmospheric visual layer */}
      <div className={styles.skyAtmosphere} aria-hidden="true">
        <div className={`${styles.star} ${styles.star1}`} />
        <div className={`${styles.star} ${styles.star2}`} />
        <div className={`${styles.star} ${styles.star3}`} />
        <div className={`${styles.star} ${styles.star4}`} />
        <div className={styles.crescentGlow} />
        <div className={styles.moonCrescent} />
        <svg
          className={styles.mountainBackdrop}
          viewBox="0 0 600 120"
          preserveAspectRatio="none"
          fill="currentColor"
        >
          <path d="M0 120 L120 70 L240 100 L380 40 L490 85 L600 50 L600 120 Z" opacity="0.6" />
          <path d="M0 120 L180 85 L320 110 L440 65 L550 95 L600 80 L600 120 Z" opacity="0.85" />
        </svg>
      </div>

      <div className={styles.content}>
        {/* Top Header Strip */}
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <div className={styles.iconBadge}>
              <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            </div>
            <div>
              <div className={styles.eyebrow}>AUTONOMOUS FORM-FILL</div>
              <h2 className={styles.title}>Night Batch Mode</h2>
              <p className={styles.configSummary}>
                {finalSize} job{finalSize === 1 ? "" : "s"} · {minMatchScore}% floor
                {tierGuardrails ? " · Tier-1 held" : ""}
              </p>
            </div>
          </div>

          <div className={styles.statusBadge} data-live={isLive ? "true" : "false"}>
            <span className={styles.statusDot} />
            <span>{isLive ? "Running" : "Ready"}</span>
          </div>
        </div>

        {/* Live Progress Banner when Batch is Active */}
        {isLive && (
          <div className={styles.liveBanner}>
            <div className={styles.liveBannerTop}>
              <div className={styles.liveBannerMain}>
                <div className={styles.liveJobRow}>
                  <span className={styles.signalBars} aria-hidden="true">
                    <span /><span /><span /><span /><span />
                  </span>
                  <div>
                    <div className={styles.liveJobTitle}>
                      {liveJob ? `${liveJob.company} — ${liveJob.title}` : "Processing batch applications..."}
                    </div>
                    <div className={styles.liveJobStep}>
                      {liveJob?.step ? liveJob.step : "Executing pipeline"}
                    </div>
                  </div>
                </div>

                <div className={styles.liveBannerStats}>
                  <div className={styles.statPill} title={`Resumed ${resumeCount} time${resumeCount === 1 ? "" : "s"}; ${processedCount} job(s) processed across this run`}>
                    <span>Batch {resumeCount}</span> <strong>{processedCount} processed</strong>
                  </div>
                  <div className={styles.statPill} data-tone="success">
                    <span>Submitted</span> <strong>{submittedCount}</strong>
                  </div>
                  {stagedCount > 0 && (
                    <div className={styles.statPill} data-tone="warning">
                      <span>Needs review</span> <strong>{stagedCount}</strong>
                    </div>
                  )}
                </div>

                <div className={styles.progressBarWrap}>
                  <div className={styles.progressBarFill} style={{ transform: `scaleX(${progressPercent / 100})` }} />
                </div>

                {/* Live pipeline — the same checkpoint sequence the runner emits,
                    so the card shows where inside one application the batch is,
                    not just that it is busy. */}
                <div className={styles.livePipeline} role="list" aria-label="Application pipeline">
                  {PIPELINE_STAGES.map((stage, i) => (
                    <React.Fragment key={stage.id}>
                      <div
                        role="listitem"
                        className={styles.liveStage}
                        data-state={
                          stageIndex < 0 ? "idle" : i < stageIndex ? "done" : i === stageIndex ? "active" : "idle"
                        }
                      >
                        <span className={styles.liveStageDot} aria-hidden="true">
                          {stageIndex >= 0 && i < stageIndex ? "✓" : i === stageIndex ? "◉" : "○"}
                        </span>
                        <span className={styles.liveStageLabel}>{stage.label}</span>
                      </div>
                      {i < PIPELINE_STAGES.length - 1 && (
                        <span
                          className={styles.liveStageLink}
                          data-done={stageIndex >= 0 && i < stageIndex ? "true" : "false"}
                          aria-hidden="true"
                        />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </div>

            {healing && ["analyzing", "patching", "requeuing"].includes(healing.status) && (
              <div className={styles.healingNote} role="status">
                <span aria-hidden="true">↻</span> Self-healing: {healing.status} · round{" "}
                {healing.currentRound} of {healing.maxRounds}
                {healing.lastPatchSummary ? ` — ${healing.lastPatchSummary}` : ""}
              </div>
            )}

            {/* Streaming activity. The runner pushes these over SSE, so this
                fills in as the application progresses instead of only after. */}
            {logs.length > 0 && (
              <div className={styles.liveFeed} aria-live="polite" aria-label="Live batch activity">
                {logs.slice(-6).map((log) => (
                  <div key={log.id} className={styles.liveFeedRow} data-level={log.level}>
                    <span className={styles.liveFeedTime}>
                      {new Date(log.timestamp).toLocaleTimeString(undefined, {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                        hour12: false,
                      })}
                    </span>
                    <span className={styles.liveFeedMsg}>{log.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Configuration Controls Grid (when idle) */}
        {!isLive && (
          <div className={styles.controlsGrid}>
            {/* Two dropdowns, one row.
                The card had a chip row for batch size, a four-card model
                picker, a histogram and a slider stacked on top of each other,
                which buried the two numbers that actually decide a run. The
                model is no longer chosen here at all - it follows the
                CAREEROS_LOCAL_LLM setting, so offering it twice invited the two
                to disagree. */}
            <div className={styles.selectRow}>
              <div className={styles.selectField}>
                <span className={styles.controlLabel} id="night-batch-size-label">
                  Jobs per run
                </span>
                {/* Side by side: there are only four sizes and the choice is the
                    one people change most, so it is worth showing all of them
                    rather than hiding three behind a menu. */}
                <div className={styles.segmented} role="radiogroup" aria-labelledby="night-batch-size-label">
                  {BATCH_SIZE_PRESETS.map((size) => (
                    <button
                      key={size}
                      type="button"
                      role="radio"
                      aria-checked={batchSize === size}
                      className={styles.segment}
                      data-active={batchSize === size}
                      onClick={() => setBatchSize(size)}
                    >
                      {size}
                    </button>
                  ))}
                </div>
              </div>

              <div className={styles.selectField}>
                <label className={styles.controlLabel} htmlFor="night-batch-floor">
                  Minimum match score
                </label>
                {/* The chevron is drawn by the wrapper rather than as a
                    background image on the select: a data-URI background is
                    unreliable across browsers once appearance is stripped, and
                    it rendered as a blank control in Firefox. */}
                <span className={styles.selectWrap}>
                  <select
                    id="night-batch-floor"
                    className={styles.nbSelect}
                    value={String(minMatchScore)}
                    onChange={(e) => setMinMatchScore(Number(e.target.value))}
                  >
                    {MATCH_FLOORS.map((floor) => (
                      <option key={floor} value={floor}>
                        {floor}% and above
                        {queueScores.length
                          ? ` (${(floorCounts.get(floor) ?? 0).toLocaleString()})`
                          : ""}
                      </option>
                    ))}
                  </select>
                </span>
              </div>
            </div>

            {/* The floor is the setting most likely to make a run do nothing,
                so its consequence stays - as one line rather than a chart. */}
            {(queueScores.length === 0 || shortfall) && (
              <p className={styles.floorReach} data-warn={shortfall ? "true" : "false"}>
                {queueScores.length === 0 ? (
                  queueLoading ? (
                    <>Reading the queue…</>
                  ) : (
                    <>Queue is empty — nothing to measure the floor against yet.</>
                  )
                ) : (
                  <>
                    Only <strong>{eligibleCount}</strong> queued job
                    {eligibleCount === 1 ? "" : "s"} clear {minMatchScore}% — fewer than the{" "}
                    {finalSize} this batch asks for.
                  </>
                )}
              </p>
            )}

            {/* Guardrails */}
            <div className={styles.auxControlsRow}>
              <label className={styles.toggleRow}>
                <input
                  type="checkbox"
                  checked={tierGuardrails}
                  onChange={(e) => setTierGuardrails(e.target.checked)}
                  className={styles.checkbox}
                />
                <span className={styles.toggleLabel}>
                  <strong>Tier-1 Guardrails:</strong> Protect Top-20 companies (Google, Microsoft, Amazon, Meta, etc.) for manual apply
                </span>
              </label>

              <label className={styles.toggleRow}>
                <input
                  type="checkbox"
                  checked={selfHealing}
                  onChange={(e) => setSelfHealing(e.target.checked)}
                  className={styles.checkbox}
                />
                <span className={styles.toggleLabel}>
                  <strong>Post-batch self-healing:</strong> let the local model diagnose this run&rsquo;s failures once it finishes
                </span>
              </label>
            </div>
          </div>
        )}

        {/* Action Footer */}
        <div className={styles.actionsFooter}>
          <div className={styles.footerNote}>
            {isLive ? (
              <span>Workers operating sequentially with Playwright Chromium & receipt verification.</span>
            ) : (
              <span>Ready to run <strong>{finalSize}</strong> jobs at a <strong>{minMatchScore}%</strong> match floor.</span>
            )}
          </div>

          <div className={styles.buttonGroup}>
            {isLive ? (
              <>
                {onPause && (
                  <button
                    type="button"
                    className={styles.btnSecondary}
                    onClick={() => void onPause()}
                    disabled={busy}
                  >
                    Pause
                  </button>
                )}
                {onStop && (
                  <button
                    type="button"
                    className={styles.btnDanger}
                    onClick={() => void onStop()}
                    disabled={busy}
                  >
                    Stop Run
                  </button>
                )}
              </>
            ) : (
              <button
                type="button"
                id="start-night-batch-btn"
                className={styles.btnPrimary}
                onClick={handleStart}
                disabled={busy}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                  <path d="M8 5v14l11-7z" />
                </svg>
                {busy ? "Starting Night Batch…" : `Start Night Batch (${finalSize} Jobs)`}
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
