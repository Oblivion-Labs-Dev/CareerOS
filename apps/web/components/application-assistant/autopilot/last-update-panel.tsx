"use client";

import React from "react";
import styles from "./last-update-panel.module.css";
import { statusView } from "./job-presentation";

/**
 * What happened most recently, standing beside the Night Batch card.
 *
 * This lived inside the card's header, where a long staging reason stretched
 * the header and pushed the whole card into a horizontal scroll. It is really a
 * different thing from the run configuration anyway — one is what you are about
 * to do, the other is what already happened — so it gets its own column.
 *
 * It reports the last application to move whatever moved it: a batch
 * submission, a single Apply, something staged for review, or a failure. A run
 * summary alone went stale the moment anything happened outside a batch.
 */

export type LastActivity = {
  company?: string;
  title?: string;
  status?: string;
  updatedAt?: string;
  reason?: string;
} | null;

export type LastRun = {
  status?: string;
  processedCount?: number;
  targetProcessCount?: number;
  submittedCount?: number;
  stagedCount?: number;
  failedCount?: number;
  skippedCount?: number;
  ineligibleCount?: number;
  completedAt?: string | null;
  stoppedAt?: string | null;
} | null;

/** "12 min ago" / "3 hrs ago" / "2 days ago". */
function timeAgo(when?: string | null): string {
  if (!when) return "";
  const ms = Date.now() - new Date(when).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  const mins = Math.round(ms / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr${hrs === 1 ? "" : "s"} ago`;
  const days = Math.round(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function describeFinish(run: NonNullable<LastRun>): string {
  const when = run.stoppedAt || run.completedAt;
  const verb = run.stoppedAt || run.status === "STOPPED" ? "Stopped" : "Finished";
  const ago = timeAgo(when);
  return ago ? `${verb} ${ago}` : verb;
}

export function LastUpdatePanel({
  lastActivity,
  lastRun,
  isLive,
}: {
  lastActivity: LastActivity;
  lastRun: LastRun;
  isLive: boolean;
}) {
  const hasRun = !!lastRun && (lastRun.processedCount || 0) > 0;
  const view = lastActivity ? statusView(lastActivity.status) : null;

  return (
    <aside className={styles.panel} aria-label="Last update">
      <div className={styles.head}>
        <span className={styles.kicker}>Last update</span>
        {lastActivity?.updatedAt && (
          <span className={styles.when}>{timeAgo(lastActivity.updatedAt)}</span>
        )}
      </div>

      {isLive ? (
        <p className={styles.empty}>A batch is running — this fills in as applications finish.</p>
      ) : !lastActivity ? (
        <p className={styles.empty}>Nothing has run yet.</p>
      ) : (
        <div className={styles.activity}>
          <span className={styles.badge} data-kind={view?.key}>
            {view?.label}
          </span>
          <p className={styles.what}>
            <strong>{lastActivity.company || "Unknown company"}</strong>
            {lastActivity.title ? <span>{lastActivity.title}</span> : null}
          </p>
          {lastActivity.reason ? <p className={styles.reason}>{lastActivity.reason}</p> : null}
        </div>
      )}

      {hasRun && lastRun && (
        <div className={styles.runBlock}>
          <div className={styles.runHead}>
            <span>Last run</span>
            <span className={styles.when}>{describeFinish(lastRun)}</span>
          </div>
          <ul className={styles.stats}>
            <li data-tone="total">
              <strong>{lastRun.processedCount}</strong> processed
            </li>
            <li data-tone="success">
              <strong>{lastRun.submittedCount || 0}</strong> submitted
            </li>
            {(lastRun.stagedCount || 0) > 0 && (
              <li data-tone="warning">
                <strong>{lastRun.stagedCount}</strong> review
              </li>
            )}
            {(lastRun.failedCount || 0) > 0 && (
              <li data-tone="danger">
                <strong>{lastRun.failedCount}</strong> failed
              </li>
            )}
            {(lastRun.ineligibleCount || 0) > 0 && (
              <li data-tone="muted">
                <strong>{lastRun.ineligibleCount}</strong> ineligible
              </li>
            )}
          </ul>
        </div>
      )}
    </aside>
  );
}
