"use client";

import React, { useState } from "react";
import styles from "./diagnostic.module.css";
import type { LiveRunRecord, RunTimelineResponse } from "@/lib/diagnostic-api";
import { fetchRunTimeline } from "@/lib/diagnostic-api";

interface LiveRunsTableProps {
  runs: LiveRunRecord[];
  activeRunId: string | null;
  loading?: boolean;
}

export function LiveRunsTable({ runs, activeRunId, loading = false }: LiveRunsTableProps) {
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  const [timelineData, setTimelineData] = useState<RunTimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);

  const handleRowClick = async (runId: string) => {
    if (expandedRunId === runId) {
      setExpandedRunId(null);
      setTimelineData(null);
      return;
    }

    setExpandedRunId(runId);
    setTimelineLoading(true);
    try {
      const data = await fetchRunTimeline(runId);
      setTimelineData(data);
    } catch {
      setTimelineData(null);
    } finally {
      setTimelineLoading(false);
    }
  };

  return (
    <section className={styles.sectionCard} aria-label="Live and Recent Runs">
      <div className={styles.cardHeader}>
        <div className={styles.headerLeft}>
          <h2 className={styles.cardTitle}>Live &amp; Recent Runs</h2>
          <span className={styles.subtext}>
            Click a run to inspect its recorded checkpoints and available timings.
          </span>
        </div>
      </div>

      <div className={styles.tableScroll}>
        <table className={styles.dataTable}>
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Current / Target</th>
              <th>State</th>
              <th>Workflow Step</th>
              <th>Duration</th>
              <th>Provider / Model</th>
              <th>Retries</th>
              <th>Submitted</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={8} className={styles.emptyTable}>
                  No Autopilot runs recorded.
                </td>
              </tr>
            ) : (
              runs.map((run) => {
                const isExpanded = expandedRunId === run.runId;
                return (
                  <React.Fragment key={run.runId}>
                    <tr
                      onClick={() => handleRowClick(run.runId)}
                      className={`${styles.clickableRow} ${isExpanded ? styles.expandedRow : ""}`}
                      aria-expanded={isExpanded}
                    >
                      <td className={styles.monoCell}>
                        <span className={styles.expandChevron}>{isExpanded ? "▼" : "▶"}</span>
                        {run.runId.slice(0, 16)}…
                      </td>
                      <td>
                        <strong className={styles.runJobText}>{run.currentJob}</strong>
                        <div className={styles.smallSubtext}>
                          Target: {run.processedCount} / {run.targetCount}
                        </div>
                      </td>
                      <td>
                        <span className={styles.statusBadge} data-state={run.state.toLowerCase()}>
                          {run.state}
                        </span>
                      </td>
                      <td>
                        <span className={styles.stepBadge}>{run.workflowStep}</span>
                      </td>
                      <td className={styles.monoCell}>{run.durationSec}s</td>
                      <td className={styles.monoCell}>{run.model || run.provider}</td>
                      <td>{run.retries}</td>
                      <td>
                        <strong className={styles.submittedCountText}>
                          {run.submittedCount}
                        </strong>
                      </td>
                    </tr>

                    {isExpanded && (
                      <tr className={styles.timelineRow}>
                        <td colSpan={8}>
                          <div className={styles.timelinePanel}>
                            <h3 className={styles.timelineHeader}>
                              Workflow Execution Timeline — {run.currentJob}
                            </h3>
                            {timelineLoading ? (
                              <p className={styles.smallSubtext}>Loading run timeline…</p>
                            ) : timelineData ? (
                              <div className={styles.timelineList}>{!timelineData.timeline.length&&<p>No checkpoints recorded for this run.</p>}
                                {timelineData.timeline.map((item, idx) => (
                                  <div key={`${item.stage}-${idx}`} className={styles.timelineItem}>
                                    <div className={styles.timelineStepHeader}>
                                      <span className={styles.timelineStepMarker}>{item.status === "failed" ? "×" : "✓"}</span>
                                      <strong className={styles.timelineStepName}>{item.stage}</strong>
                                      <span className={styles.timelineStepLabel}>({item.label})</span>
                                      <span className={styles.timelineDuration}>{item.durationMs == null ? "Timing not recorded" : `${item.durationMs}ms`}</span>
                                    </div>
                                    <p className={styles.timelineStepDetails}>{item.details}</p>
                                    <span className={styles.timelineTimestamp}>
                                      {new Date(item.timestamp).toLocaleTimeString()}
                                    </span>
                                    {idx < timelineData.timeline.length - 1 && (
                                      <div className={styles.timelineConnector}>↓</div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className={styles.smallSubtext}>Timeline details unavailable for this run.</p>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
