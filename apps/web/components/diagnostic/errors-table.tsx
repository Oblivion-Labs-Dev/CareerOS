"use client";

import React, { useState } from "react";
import styles from "./diagnostic.module.css";
import type { DiagnosticErrorItem } from "@/lib/diagnostic-api";

interface ErrorsTableProps {
  errors: DiagnosticErrorItem[];
  severity: string;
  service: string;
  search: string;
  onSeverityChange: (s: string) => void;
  onServiceChange: (s: string) => void;
  onSearchChange: (s: string) => void;
  loading?: boolean;
}

export function ErrorsTable({
  errors,
  severity,
  service,
  search,
  onSeverityChange,
  onServiceChange,
  onSearchChange,
  loading = false,
}: ErrorsTableProps) {
  const [expandedErrorId, setExpandedErrorId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpandedErrorId((curr) => (curr === id ? null : id));
  };

  return (
    <section className={styles.sectionCard} aria-label="System Errors">
      <div className={styles.cardHeader}>
        <div className={styles.headerLeft}>
          <h2 className={styles.cardTitle}>Errors Log</h2>
          <span className={styles.subtext}>
            Searchable &amp; filterable error ledger with trace/span correlation IDs
          </span>
        </div>
      </div>

      <div className={styles.filterRow}>
        <input
          type="text"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search by error text, trace ID, run ID, or stage…"
          className={styles.filterSearchInput}
        />

        <div className={styles.filterGroup}>
          <label htmlFor="severity-select" className={styles.filterLabel}>Severity:</label>
          <select
            id="severity-select"
            value={severity}
            onChange={(e) => onSeverityChange(e.target.value)}
            className={styles.filterSelect}
          >
            <option value="all">All Severities</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
            <option value="critical">Critical</option>
          </select>
        </div>

        <div className={styles.filterGroup}>
          <label htmlFor="service-select" className={styles.filterLabel}>Service:</label>
          <select
            id="service-select"
            value={service}
            onChange={(e) => onServiceChange(e.target.value)}
            className={styles.filterSelect}
          >
            <option value="all">All Services</option>
            <option value="autopilot">Autopilot</option>
            <option value="careeros_api">CareerOS API</option>
            <option value="playwright_worker">Playwright</option>
            <option value="ollama">Ollama</option>
            <option value="qwen">Qwen</option>
            <option value="gemini">Gemini</option>
          </select>
        </div>
      </div>

      <div className={styles.tableScroll}>
        <table className={styles.dataTable}>
          <thead>
            <tr>
              <th>Time</th>
              <th>Severity</th>
              <th>Service</th>
              <th>Application</th>
              <th>Stage</th>
              <th>Error</th>
              <th>Retries</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {errors.length === 0 ? (
              <tr>
                <td colSpan={8} className={styles.emptyTable}>
                  No errors match the current filter criteria.
                </td>
              </tr>
            ) : (
              errors.map((err) => {
                const isExpanded = expandedErrorId === err.id;
                return (
                  <React.Fragment key={err.id}>
                    <tr
                      onClick={() => toggleExpand(err.id)}
                      className={`${styles.clickableRow} ${isExpanded ? styles.expandedRow : ""}`}
                      aria-expanded={isExpanded}
                    >
                      <td className={styles.monoCell}>
                        <span className={styles.expandChevron}>{isExpanded ? "▼" : "▶"}</span>
                        {new Date(err.time).toLocaleTimeString()}
                      </td>
                      <td>
                        <span className={styles.severityBadge} data-severity={err.severity}>
                          {err.severity}
                        </span>
                      </td>
                      <td className={styles.serviceNameCell}>{err.service}</td>
                      <td className={styles.monoCell}>
                        {err.applicationId ? err.applicationId.slice(0, 12) + "…" : "—"}
                      </td>
                      <td>
                        <span className={styles.stageTag}>{err.stage || "—"}</span>
                      </td>
                      <td className={styles.errorMessageCell}>
                        <span className={styles.errorSnippet}>{err.error}</span>
                      </td>
                      <td>{err.retries}</td>
                      <td>
                        <span className={styles.errorStatusTag} data-status={err.status}>
                          {err.status}
                        </span>
                      </td>
                    </tr>

                    {isExpanded && (
                      <tr className={styles.errorDetailRow}>
                        <td colSpan={8}>
                          <div className={styles.errorDetailPanel}>
                            <div className={styles.correlationRow}>
                              <div>
                                <strong>Trace ID:</strong>{" "}
                                <code>{err.traceId || "trace_unassigned"}</code>
                              </div>
                              <div>
                                <strong>Run ID:</strong>{" "}
                                <code>{err.runId || "run_unassigned"}</code>
                              </div>
                              <div>
                                <strong>Job ID:</strong>{" "}
                                <code>{err.jobId || "job_unassigned"}</code>
                              </div>
                              <div>
                                <strong>Provider / Model:</strong>{" "}
                                <code>{err.provider || "ollama"} / {err.model || "qwen"}</code>
                              </div>
                            </div>

                            {err.stackTrace && (
                              <div className={styles.codeBlockWrap}>
                                <strong>Stack Trace:</strong>
                                <pre className={styles.codeBlock}>{err.stackTrace}</pre>
                              </div>
                            )}

                            {err.playwrightError && (
                              <div className={styles.codeBlockWrap}>
                                <strong>Playwright Error:</strong>
                                <pre className={styles.codeBlock}>{err.playwrightError}</pre>
                              </div>
                            )}

                            {err.screenshotPath && (
                              <div className={styles.detailRowItem}>
                                <strong>Screenshot Path:</strong> <code>{err.screenshotPath}</code>
                              </div>
                            )}

                            {err.logs && err.logs.length > 0 && (
                              <div className={styles.codeBlockWrap}>
                                <strong>Context Logs:</strong>
                                <pre className={styles.codeBlock}>{err.logs.join("\n")}</pre>
                              </div>
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
