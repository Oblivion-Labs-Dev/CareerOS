"use client";

import { useMemo, useState } from "react";
import { StatusDot } from "./bits";
import { priorityLabel, timeAgo } from "./format";
import type { MarketHealth, MarketPulse, StatusBucket } from "./types";
import styles from "./markets.module.css";

const BUCKETS: StatusBucket[] = ["healthy", "degraded", "failed", "manual", "pending"];

export function SourceHealth({
  health,
  pulse,
  refreshingIds,
  marketRunning,
  onRetry,
  onOpenCompany,
}: {
  health: MarketHealth;
  pulse: MarketPulse;
  refreshingIds: Set<string>;
  marketRunning: boolean;
  onRetry: (id: string) => void;
  onOpenCompany: (id: string) => void;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const rows = useMemo(
    () => health.needsAttention.filter((r) => !problem || r.problem === problem),
    [health.needsAttention, problem],
  );

  return (
    <>
      <div className={styles.healthGrid}>
        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <h3>Coverage</h3>
            <span className={styles.resultCount}>{pulse.autoSearchable} of {pulse.companies} auto-searchable</span>
          </div>
          <div className={styles.problemList}>
            {health.problems.length === 0 ? (
              <div className={styles.empty}><strong>Every source is healthy</strong></div>
            ) : (
              health.problems.map((p) => (
                <button
                  key={p.problem}
                  type="button"
                  className={styles.problem}
                  aria-pressed={problem === p.problem}
                  onClick={() => setProblem(problem === p.problem ? null : p.problem)}
                >
                  <StatusDot status={p.problem === "Scan failed" ? "failed" : p.problem === "Career URL changed" ? "degraded" : "manual"} />
                  {p.problem}
                  <b>{p.count}</b>
                </button>
              ))
            )}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHead}><h3>By source</h3></div>
          {health.sources.map((s) => (
            <div key={s.source} className={styles.sourceRow}>
              <span>{s.source}</span>
              <span className={styles.stack} title={BUCKETS.filter((b) => s[b]).map((b) => `${s[b]} ${b}`).join(", ")}>
                {BUCKETS.map((b) => (s[b] ? <i key={b} data-s={b} style={{ width: `${(100 * (s[b] ?? 0)) / s.total}%` }} /> : null))}
              </span>
              <b>{s.total}</b>
            </div>
          ))}
        </div>
      </div>

      <div className={styles.panel}>
        <div className={styles.panelHead}>
          <h3>Needs attention</h3>
          <span className={styles.resultCount}>
            {rows.length} {problem ? `· ${problem}` : "companies"}
            {problem ? <> · <button type="button" className={styles.clear} onClick={() => setProblem(null)}>Show all</button></> : null}
          </span>
        </div>
        {rows.length === 0 ? (
          <div className={styles.empty}><strong>Nothing needs attention</strong><p>Every tracked company&apos;s jobs are being read automatically.</p></div>
        ) : (
          rows.map((r) => (
            <div key={r.companyId} className={styles.attnRow}>
              <span className={styles.rank}>{priorityLabel(r.priority)}</span>
              <div className={styles.companyCell}>
                <button type="button" className={styles.clear} style={{ color: "var(--text)", fontWeight: 650, fontSize: "var(--text-sm)" }} onClick={() => onOpenCompany(r.companyId)}>
                  {r.company}
                </button>
                <div className={styles.companySub}>{r.source}{r.tier ? ` · Tier ${r.tier}` : ""}</div>
              </div>
              <span className={styles.attnProblem}><StatusDot status={r.status} />{r.problem}</span>
              <span className={styles.attnReason}>
                {r.reason || "—"}
                {r.otherSources ? ` · ${r.otherSources} relevant from other sources` : ""}
                {r.lastAttemptAt ? ` · tried ${timeAgo(r.lastAttemptAt)}` : ""}
              </span>
              <span className={styles.oppActions}>
                <button type="button" className={styles.mini} disabled={marketRunning || refreshingIds.has(r.companyId)} onClick={() => onRetry(r.companyId)}>
                  {refreshingIds.has(r.companyId) ? "Retrying…" : "Retry"}
                </button>
                {r.url ? <a className={styles.mini} href={r.url} target="_blank" rel="noreferrer">Open Career Site ↗</a> : null}
              </span>
            </div>
          ))
        )}
      </div>
    </>
  );
}
