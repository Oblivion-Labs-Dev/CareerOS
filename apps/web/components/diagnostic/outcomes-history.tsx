"use client";

import React, { useMemo, useState } from "react";
import styles from "./diagnostic.module.css";
import type {
  OutcomeKind,
  OutcomeReasonCount,
  OutcomesReport,
} from "@/lib/diagnostic-api";

export const MAX_REPORT_DAYS = 30;
const PRESETS = ["1h", "12h", "24h", "7d", "14d", "30d"] as const;

const OUTCOME_LABELS: Record<OutcomeKind, string> = {
  SUBMITTED: "Submitted",
  STAGED: "Staged for review",
  FAILED: "Failed",
  SKIPPED: "Skipped / held",
};

const STATUS_LABELS: Record<string, string> = {
  SUBMITTED: "Submitted",
  NEEDS_REVIEW: "Needs review",
  MANUAL_REVIEW: "Manual review",
  INELIGIBLE: "Ineligible",
  FAILED: "Failed",
  SKIPPED: "Skipped",
  QUEUED: "Queued",
  APPLYING: "Applying",
};

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  if (sec < 60) return `${sec < 10 ? sec.toFixed(1) : Math.round(sec)}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s`;
  return `${Math.floor(sec / 3600)}h ${Math.round((sec % 3600) / 60)}m`;
}

interface OutcomesHistoryProps {
  report: OutcomesReport | null;
  period: string;
  onPeriodChange: (period: string) => void;
  loading?: boolean;
}

function ReasonPanel({
  title,
  reasons,
  tone,
}: {
  title: string;
  reasons: OutcomeReasonCount[];
  tone?: "warning" | "danger" | "success";
}) {
  const total = reasons.reduce((sum, r) => sum + r.count, 0);
  const max = reasons.length ? reasons[0].count : 0;
  return (
    <div className={styles.reasonPanel} data-tone={tone}>
      <div className={styles.reasonPanelTitle}>
        <span>{title}</span>
        <span className={styles.reasonPanelTotal}>{total} in top reasons</span>
      </div>
      {reasons.length === 0 ? (
        <p className={styles.reasonEmpty}>None in this window.</p>
      ) : (
        <div className={styles.reasonList}>
          {reasons.map((r) => (
            <div className={styles.reasonRow} key={r.reason} title={r.exampleUrl || undefined}>
              <span className={styles.reasonRowLabel}>{r.reason}</span>
              <span className={styles.reasonRowCount}>{r.count}</span>
              <div className={styles.reasonBarTrack}>
                <div
                  className={styles.reasonBarFill}
                  style={{ width: max > 0 ? `${Math.max(4, (r.count / max) * 100)}%` : "0%" }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PeriodPicker({ period, onChange }: { period: string; onChange: (p: string) => void }) {
  const [amount, setAmount] = useState("3");
  const [unit, setUnit] = useState<"h" | "d">("d");
  const [error, setError] = useState("");

  const applyCustom = () => {
    const n = Number(amount);
    if (!Number.isInteger(n) || n < 1) {
      setError("Enter a whole number of 1 or more.");
      return;
    }
    const hours = unit === "d" ? n * 24 : n;
    if (hours > MAX_REPORT_DAYS * 24) {
      setError(`Reports cover up to ${MAX_REPORT_DAYS} days.`);
      return;
    }
    setError("");
    onChange(`${n}${unit}`);
  };

  return (
    <div className={styles.periodControls}>
      <div className={styles.periodSelector} role="radiogroup" aria-label="Report window">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={period === p}
            onClick={() => onChange(p)}
            className={`${styles.periodButton} ${period === p ? styles.periodActive : ""}`}
          >
            {p}
          </button>
        ))}
      </div>
      <form
        className={styles.customPeriod}
        onSubmit={(e) => {
          e.preventDefault();
          applyCustom();
        }}
      >
        <label htmlFor="custom-period-amount" className={styles.filterLabel}>Last</label>
        <input
          id="custom-period-amount"
          type="number"
          min={1}
          max={unit === "d" ? MAX_REPORT_DAYS : MAX_REPORT_DAYS * 24}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className={styles.customPeriodInput}
        />
        <select
          aria-label="Unit"
          value={unit}
          onChange={(e) => setUnit(e.target.value as "h" | "d")}
          className={styles.filterSelect}
        >
          <option value="h">hours</option>
          <option value="d">days</option>
        </select>
        <button type="submit" className={styles.periodButton}>Apply</button>
        {error && <span className={styles.customPeriodError} role="alert">{error}</span>}
      </form>
    </div>
  );
}

function SeriesChart({ report }: { report: OutcomesReport }) {
  const max = Math.max(
    1,
    ...report.series.map((b) => b.SUBMITTED + b.STAGED + b.FAILED + b.SKIPPED),
  );
  const label = (bucket: string) =>
    report.bucketUnit === "hour"
      ? new Date(bucket).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" })
      : new Date(`${bucket}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const first = report.series[0];
  const middle = report.series[Math.floor(report.series.length / 2)];
  const last = report.series[report.series.length - 1];

  return (
    <div className={styles.seriesWrap}>
      <div className={styles.seriesLegend}>
        {(Object.keys(OUTCOME_LABELS) as OutcomeKind[]).map((o) => (
          <span key={o} className={styles.seriesLegendItem}>
            <span className={styles.seriesSwatch} data-outcome={o} />
            {OUTCOME_LABELS[o]}
          </span>
        ))}
      </div>
      <div className={styles.seriesScroll}>
        <div className={styles.seriesChart} role="img" aria-label={`Outcomes per ${report.bucketUnit}`}>
          {report.series.map((b) => {
            const total = b.SUBMITTED + b.STAGED + b.FAILED + b.SKIPPED;
            return (
              <div
                key={b.bucket}
                className={styles.seriesCol}
                title={`${label(b.bucket)}: ${b.SUBMITTED} submitted, ${b.STAGED} staged, ${b.FAILED} failed, ${b.SKIPPED} skipped`}
              >
                {(["SKIPPED", "FAILED", "STAGED", "SUBMITTED"] as OutcomeKind[]).map((o) =>
                  b[o] > 0 ? (
                    <div
                      key={o}
                      className={styles.seriesSeg}
                      data-outcome={o}
                      style={{ height: `${(b[o] / max) * 100}%` }}
                    />
                  ) : null,
                )}
                {total === 0 && <div className={styles.seriesEmpty} />}
              </div>
            );
          })}
        </div>
      </div>
      {first && last && (
        <div className={styles.seriesAxis}>
          <span>{label(first.bucket)}</span>
          {middle && report.series.length > 2 && <span>{label(middle.bucket)}</span>}
          <span>{label(last.bucket)}</span>
        </div>
      )}
    </div>
  );
}

export function OutcomesHistory({ report, period, onPeriodChange, loading = false }: OutcomesHistoryProps) {
  const [outcomeFilter, setOutcomeFilter] = useState<"all" | OutcomeKind>("all");
  const [search, setSearch] = useState("");

  const visibleEvents = useMemo(() => {
    if (!report) return [];
    const needle = search.trim().toLowerCase();
    return report.events.filter((e) => {
      if (outcomeFilter !== "all" && e.outcome !== outcomeFilter) return false;
      if (!needle) return true;
      return `${e.company} ${e.title} ${e.reason} ${e.detail}`.toLowerCase().includes(needle);
    });
  }, [report, outcomeFilter, search]);

  const windowText = report
    ? `${new Date(report.windowStart).toLocaleString()} – ${new Date(report.windowEnd).toLocaleString()}`
    : "";

  return (
    <>
      <section className={styles.sectionCard} aria-label="Report window">
        <div className={styles.cardHeader}>
          <div className={styles.headerLeft}>
            <h2 className={styles.cardTitle}>Report Window</h2>
            <span className={styles.subtext}>
              {report ? windowText : "Loading…"} · up to {MAX_REPORT_DAYS} days
            </span>
          </div>
          <PeriodPicker period={period} onChange={onPeriodChange} />
        </div>

        <div className={styles.metricTilesGrid}>
          {(["SUBMITTED", "STAGED", "FAILED", "SKIPPED"] as OutcomeKind[]).map((o) => (
            <div
              className={styles.metricTile}
              key={o}
              data-tone={o === "SUBMITTED" ? "success" : o === "FAILED" ? "danger" : o === "STAGED" ? "warning" : undefined}
            >
              <span className={styles.metricLabel}>{OUTCOME_LABELS[o]}</span>
              <span className={styles.metricNumber}>{report ? report.windowOutcomeCounts[o] : "—"}</span>
              <span className={styles.metricHint}>Attempt outcomes in window</span>
            </div>
          ))}
          <div className={styles.metricTile} data-tone="accent">
            <span className={styles.metricLabel}>Jobs Touched</span>
            <span className={styles.metricNumber}>{report ? report.windowJobsTouched : "—"}</span>
            <span className={styles.metricHint}>Distinct postings with an outcome</span>
          </div>
          <div className={styles.metricTile}>
            <span className={styles.metricLabel}>Avg Time to Submit</span>
            <span className={styles.metricNumber}>{report ? formatDuration(report.durationStats.SUBMITTED.avgSec) : "—"}</span>
            <span className={styles.metricHint}>Claim to confirmed submission</span>
          </div>
        </div>

        {report && (
          <div className={styles.statusStrip}>
            <span className={styles.statusStripLabel}>Where those jobs are now:</span>
            {Object.entries(STATUS_LABELS).map(([key, label]) =>
              report.windowCurrentStatusCounts[key] ? (
                <span key={key} className={styles.statusChip}>
                  {label} <strong>{report.windowCurrentStatusCounts[key]}</strong>
                </span>
              ) : null,
            )}
            <span className={styles.statusStripLabel}>All-time totals:</span>
            {Object.entries(STATUS_LABELS).map(([key, label]) => (
              <span key={`all-${key}`} className={styles.statusChip}>
                {label} <strong>{report.allTimeStatusCounts[key] ?? 0}</strong>
              </span>
            ))}
          </div>
        )}
      </section>

      <section className={styles.sectionCard} aria-label="Outcomes over time">
        <div className={styles.cardHeader}>
          <div className={styles.headerLeft}>
            <h2 className={styles.cardTitle}>Outcomes Over Time</h2>
            <span className={styles.subtext}>Per {report?.bucketUnit ?? "bucket"}, UTC</span>
          </div>
        </div>
        {report ? <SeriesChart report={report} /> : <p className={styles.emptyTable}>Loading…</p>}
      </section>

      <section className={styles.sectionCard} aria-label="Time per application">
        <div className={styles.cardHeader}>
          <div className={styles.headerLeft}>
            <h2 className={styles.cardTitle}>Time Per Application</h2>
            <span className={styles.subtext}>
              Each attempt timed from claim to its outcome. Skips decided at claim time take under a second.
            </span>
          </div>
        </div>
        <div className={`${styles.tableScroll} ${styles.durationTableWrap}`}>
          <table className={styles.dataTable}>
            <thead>
              <tr>
                <th>Outcome</th>
                <th>Attempts timed</th>
                <th>Average</th>
                <th>Median</th>
                <th>P90</th>
                <th>Longest</th>
                <th>Total time</th>
              </tr>
            </thead>
            <tbody>
              {(["ALL", "SUBMITTED", "STAGED", "FAILED", "SKIPPED"] as const).map((key) => {
                const s = report?.durationStats[key];
                return (
                  <tr key={key}>
                    <td>
                      {key === "ALL" ? (
                        <strong>All attempts</strong>
                      ) : (
                        <span className={styles.outcomeBadge} data-outcome={key}>{OUTCOME_LABELS[key]}</span>
                      )}
                    </td>
                    <td className={styles.monoCell}>{s ? s.count : "—"}</td>
                    <td className={styles.monoCell}>{formatDuration(s?.avgSec)}</td>
                    <td className={styles.monoCell}>{formatDuration(s?.medianSec)}</td>
                    <td className={styles.monoCell}>{formatDuration(s?.p90Sec)}</td>
                    <td className={styles.monoCell}>{formatDuration(s?.maxSec)}</td>
                    <td className={styles.monoCell}>{s ? formatDuration(s.totalSec) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {report && report.slowestEvents.length > 0 && (
          <>
            <h3 className={styles.slowestTitle}>Slowest attempts in this window</h3>
            <div className={styles.tableScroll}>
              <table className={styles.dataTable}>
                <thead>
                  <tr>
                    <th>Duration</th>
                    <th>Finished</th>
                    <th>Company</th>
                    <th>Title</th>
                    <th>Outcome</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {report.slowestEvents.map((e, i) => (
                    <tr key={`slow-${e.jobId}-${e.timestamp}-${i}`} title={e.detail || undefined}>
                      <td className={styles.monoCell}><strong>{formatDuration(e.durationSec)}</strong></td>
                      <td className={styles.monoCell}>{new Date(e.timestamp).toLocaleString()}</td>
                      <td className={styles.runJobText}>{e.company}</td>
                      <td className={styles.smallSubtext}>{e.title}</td>
                      <td>
                        <span className={styles.outcomeBadge} data-outcome={e.outcome}>{OUTCOME_LABELS[e.outcome]}</span>
                      </td>
                      <td className={styles.smallSubtext}>{e.reason || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className={styles.sectionCard} aria-label="Why">
        <div className={styles.cardHeader}>
          <div className={styles.headerLeft}>
            <h2 className={styles.cardTitle}>Why It Happened</h2>
            <span className={styles.subtext}>
              Reasons for each attempt outcome in the window, from the checkpoint recorded at the time
            </span>
          </div>
        </div>
        <div className={styles.reasonGrid}>
          <ReasonPanel title="Staged for review" reasons={report?.windowReasons.STAGED ?? []} tone="warning" />
          <ReasonPanel title="Failed" reasons={report?.windowReasons.FAILED ?? []} tone="danger" />
          <ReasonPanel title="Skipped / held" reasons={report?.windowReasons.SKIPPED ?? []} />
          <ReasonPanel
            title="Most common blank required field"
            reasons={(report?.topBlankFields ?? []).map((f) => ({ reason: f.field, count: f.count, exampleUrl: "" }))}
          />
        </div>
      </section>

      <section className={styles.sectionCard} aria-label="Current state">
        <div className={styles.cardHeader}>
          <div className={styles.headerLeft}>
            <h2 className={styles.cardTitle}>Where They Sit Now</h2>
            <span className={styles.subtext}>
              Current status of jobs touched in the window, grouped by their latest recorded reason
            </span>
          </div>
        </div>
        <div className={styles.reasonGrid}>
          <ReasonPanel title="Manual review" reasons={report?.currentStatusReasons.MANUAL_REVIEW ?? []} tone="warning" />
          <ReasonPanel title="Needs review" reasons={report?.currentStatusReasons.NEEDS_REVIEW ?? []} tone="warning" />
          <ReasonPanel title="Failed" reasons={report?.currentStatusReasons.FAILED ?? []} tone="danger" />
          <ReasonPanel title="Ineligible" reasons={report?.currentStatusReasons.INELIGIBLE ?? []} />
        </div>
      </section>

      <section className={styles.sectionCard} aria-label="Event history">
        <div className={styles.cardHeader}>
          <div className={styles.headerLeft}>
            <h2 className={styles.cardTitle}>Event History</h2>
            <span className={styles.subtext}>
              {report
                ? `Showing ${visibleEvents.length} of ${report.events.length}` +
                  (report.eventsTruncated ? ` (newest ${report.events.length} of ${report.eventsTotal})` : "")
                : ""}
            </span>
          </div>
        </div>
        <div className={styles.filterRow}>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by company, title, or reason…"
            className={styles.filterSearchInput}
          />
          <div className={styles.filterGroup}>
            <label htmlFor="outcome-filter" className={styles.filterLabel}>Outcome:</label>
            <select
              id="outcome-filter"
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value as "all" | OutcomeKind)}
              className={styles.filterSelect}
            >
              <option value="all">All outcomes</option>
              {(Object.keys(OUTCOME_LABELS) as OutcomeKind[]).map((o) => (
                <option key={o} value={o}>{OUTCOME_LABELS[o]}</option>
              ))}
            </select>
          </div>
        </div>
        <div className={styles.tableScroll}>
          <table className={styles.dataTable}>
            <thead>
              <tr>
                <th>Time</th>
                <th>Company</th>
                <th>Title</th>
                <th>Outcome</th>
                <th>Duration</th>
                <th>Now</th>
                <th>Reason</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {visibleEvents.length === 0 ? (
                <tr>
                  <td colSpan={8} className={styles.emptyTable}>
                    {loading || !report ? "Loading…" : "No outcomes match this window and filter."}
                  </td>
                </tr>
              ) : (
                visibleEvents.map((e, i) => (
                  <tr key={`${e.jobId}-${e.timestamp}-${i}`} title={e.detail || undefined}>
                    <td className={styles.monoCell}>{new Date(e.timestamp).toLocaleString()}</td>
                    <td className={styles.runJobText}>
                      {e.applicationUrl ? (
                        <a href={e.applicationUrl} target="_blank" rel="noopener noreferrer">{e.company}</a>
                      ) : (
                        e.company
                      )}
                    </td>
                    <td className={styles.smallSubtext}>{e.title}</td>
                    <td>
                      <span className={styles.outcomeBadge} data-outcome={e.outcome}>
                        {OUTCOME_LABELS[e.outcome]}
                      </span>
                    </td>
                    <td className={styles.monoCell}>{formatDuration(e.durationSec)}</td>
                    <td className={styles.smallSubtext}>{STATUS_LABELS[e.currentStatus] ?? e.currentStatus}</td>
                    <td className={styles.smallSubtext}>
                      {e.reason || "—"}
                      {e.synthetic && <span className={styles.syntheticNote}> (no checkpoint; dated by last update)</span>}
                    </td>
                    <td className={styles.monoCell}>{e.matchScore != null ? Number(e.matchScore).toFixed(1) : "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
