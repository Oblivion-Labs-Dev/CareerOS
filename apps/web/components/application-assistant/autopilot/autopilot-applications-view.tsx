"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { SidePanelPortal } from "@/components/side-panel-portal";
import {
  approvePreflightSubmission,
  approveStagedAnswer,
  getAutopilotJobs,
  resetSubmittedAutopilotJobs,
  skipStagedApplication,
} from "@/lib/application-assistant-api";
import { LatencyDiagnosticsCenter } from "@/components/application-assistant/latency-diagnostics-center";
import type { AutopilotJobRow } from "./job-types";
import { FILTERS, SORTS, INELIGIBILITY_LABELS, priorityRank, statusView, matchBand, relativeTime, type StatusFilter, type SortMode } from "./job-presentation";
import styles from "./control-center.module.css";

type Section = "applications" | "review" | "diagnostics";
export function AutopilotApplicationsView({
  section,
  jobs,
  loading,
  onJobsChanged,
}: {
  section: Section;
  jobs: AutopilotJobRow[];
  loading: boolean;
  onJobsChanged: () => void;
}) {
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("priority");
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [detail, setDetail] = useState<AutopilotJobRow | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});
  const menuRef = useRef<HTMLDivElement>(null);
  const applyInFlight = useRef(false);

  useEffect(() => {
    if (section === "review") setFilter("review");
    else if (section === "diagnostics") setFilter("failed");
  }, [section]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menuOpen]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of FILTERS) c[f.id] = jobs.filter(f.match).length;
    return c;
  }, [jobs]);

  const visible = useMemo(() => {
    const active = FILTERS.find((f) => f.id === filter) ?? FILTERS[0];
    const q = query.trim().toLowerCase();
    return jobs
      .filter(active.match)
      .filter((j) =>
        !q ||
        [j.company, j.title, j.location, j.status, j.lastErrorType].some((v) =>
          String(v || "").toLowerCase().includes(q),
        ),
      )
      .sort((a, b) => {
        if (sortMode === "match") return Number(b.matchScore || 0) - Number(a.matchScore || 0);
        if (sortMode === "company") return String(a.company || "").localeCompare(String(b.company || ""));
        if (sortMode === "recent") {
          return String(b.submittedAt || b.updatedAt || "")
            .localeCompare(String(a.submittedAt || a.updatedAt || ""));
        }
        return priorityRank(b) - priorityRank(a);
      });
  }, [jobs, filter, query, sortMode]);

  const downloadJson = async () => {
    setMenuOpen(false);
    let all: AutopilotJobRow[] = jobs.filter((j) => j.status === "SUBMITTED");
    try {
      const res = await getAutopilotJobs("SUBMITTED", 200);
      all = (res.jobs || []) as AutopilotJobRow[];
    } catch {
      /* fall back to what's loaded */
    }
    const payload = {
      exportTimestamp: new Date().toISOString(),
      totalSubmitted: all.length,
      applications: all.map((j) => ({
        id: j.id,
        company: j.company,
        title: j.title,
        location: j.location,
        applicationUrl: j.applicationUrl,
        status: j.status,
        submittedAt: j.submittedAt || j.updatedAt,
        matchScore: j.matchScore,
        resumeFileUsed: j.resumeFileUsed,
        answers: j.answers || {},
      })),
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `careeros_submitted_${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setNote(`Exported ${all.length} submitted application(s).`);
  };

  const resetAll = async () => {
    setMenuOpen(false);
    const confirmed = window.confirm(
      "Reset ALL submitted and processed jobs back to unapplied?\n\nThis clears their submitted state so Autopilot can apply again. This cannot be undone.",
    );
    if (!confirmed) return;
    setBusy("reset");
    try {
      await resetSubmittedAutopilotJobs("ALL");
      setNote("Reset complete.");
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setBusy(null);
    }
  };

  const approveAnswers = async (job: AutopilotJobRow) => {
    const questions = job.pendingQuestions || [];
    const pairs = questions
      .map((q) => ({ key: q.rawLabel || q.question, value: (answerDrafts[`${job.id}:${q.question}`] || "").trim() }))
      .filter((p) => p.value);
    if (pairs.length === 0) {
      setNote("Enter an answer before approving.");
      return;
    }
    setBusy(job.id);
    try {
      for (const p of pairs) await approveStagedAnswer(job.id, p.key, p.value);
      await approvePreflightSubmission(job.id, undefined, "honest");
      setNote(`Approved — applying to ${job.company}.`);
      setDetail(null);
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not approve");
    } finally {
      setBusy(null);
    }
  };

  /** Same action the pre-redesign Apply button fired, kept on queued cards. */
  const applyNow = async (job: AutopilotJobRow) => {
    if (applyInFlight.current || !(job.status === "QUEUED" || (job.status === "SKIPPED" && job.skipReason?.startsWith("Match score stayed below")))) return;
    applyInFlight.current = true;
    setBusy(job.id);
    setNote(null);
    try {
      const res = await approvePreflightSubmission(job.id, undefined, "honest");
      setNote(res?.message || `Applying to ${job.company} — this can take a minute.`);
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Failed to apply");
    } finally {
      applyInFlight.current = false;
      setBusy(null);
    }
  };

  const skipJob = async (job: AutopilotJobRow) => {
    setBusy(job.id);
    try {
      await skipStagedApplication(job.id, "Skipped from Autopilot review");
      setNote(`Skipped ${job.company}.`);
      setDetail(null);
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not skip");
    } finally {
      setBusy(null);
    }
  };

  // ── Review workflow ──
  if (section === "review") {
    const reviewJobs = jobs.filter((j) => j.status === "NEEDS_REVIEW" || j.status === "STAGED");
    return (
      <div className={styles.mainCol}>
        {note && <div className={styles.empty}>{note}</div>}
        {loading ? (
          <p className={styles.loadingText}>Loading review queue…</p>
        ) : reviewJobs.length === 0 ? (
          <div className={styles.empty}>
            Nothing is waiting on you. Autopilot stages an application here only when it can&apos;t answer
            something safely on its own.
          </div>
        ) : (
          reviewJobs.map((job) => {
            const questions = job.pendingQuestions || [];
            return (
              <section key={job.id} className={styles.reviewCard}>
                <div className={styles.reviewCompany}>{job.company || "Unknown company"}</div>
                <div className={styles.reviewRole}>{job.title || "Unknown role"}</div>

                {questions.length > 0 ? (
                  questions.map((q) => (
                    <div key={q.question}>
                      <div className={styles.reviewQuestion}>
                        <span className={styles.reviewMetaLabel}>Question</span>
                        {q.question}
                      </div>
                      {q.options && q.options.length > 0 ? (
                        <select
                          className={styles.searchInput}
                          style={{ marginTop: "0.6rem", maxWidth: "100%", width: "100%" }}
                          value={answerDrafts[`${job.id}:${q.question}`] || ""}
                          onChange={(e) =>
                            setAnswerDrafts((prev) => ({ ...prev, [`${job.id}:${q.question}`]: e.target.value }))
                          }
                        >
                          <option value="">Select an answer…</option>
                          {q.options.map((o) => (
                            <option key={o} value={o}>{o}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="text"
                          className={styles.searchInput}
                          style={{ marginTop: "0.6rem", maxWidth: "100%", width: "100%" }}
                          placeholder="Your answer…"
                          value={answerDrafts[`${job.id}:${q.question}`] || ""}
                          onChange={(e) =>
                            setAnswerDrafts((prev) => ({ ...prev, [`${job.id}:${q.question}`]: e.target.value }))
                          }
                        />
                      )}
                    </div>
                  ))
                ) : (
                  <div className={styles.reviewQuestion}>
                    <span className={styles.reviewMetaLabel}>Why Autopilot stopped</span>
                    {job.lastError || "Staged for human review."}
                  </div>
                )}

                <p className={styles.reviewReason}>
                  <span className={styles.reviewMetaLabel}>Reason for review</span>
                  Autopilot found no deterministic answer in your CareerOS profile, so it stopped rather than
                  guessing on a real application.
                </p>

                <div className={styles.reviewActions}>
                  <button
                    type="button"
                    className={`${styles.filterChip} ${styles.filterChipActive}`}
                    disabled={busy === job.id}
                    onClick={() => void approveAnswers(job)}
                  >
                    {busy === job.id ? "Applying…" : "Approve & continue"}
                  </button>
                  <button type="button" className={styles.filterChip} disabled={busy === job.id} onClick={() => void skipJob(job)}>
                    Skip application
                  </button>
                </div>
              </section>
            );
          })
        )}
      </div>
    );
  }

  // ── Applications + Diagnostics (shared card grid, different detail emphasis) ──
  return (
    <div>
      {section === "diagnostics" && (
        <div style={{ marginBottom: "1rem" }}>
          <LatencyDiagnosticsCenter />
        </div>
      )}

      <div className={styles.filterBar}>
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            className={`${styles.filterChip} ${filter === f.id ? styles.filterChipActive : ""}`}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
            <span style={{ opacity: 0.7 }}>{counts[f.id] ?? 0}</span>
          </button>
        ))}

        <input
          type="text"
          className={styles.searchInput}
          placeholder="Search company, role, location…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />

        <select
          className={styles.searchInput}
          style={{ maxWidth: "13rem" }}
          value={sortMode}
          onChange={(e) => setSortMode(e.target.value as SortMode)}
          aria-label="Sort applications"
        >
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>

        <div className={styles.overflowWrap} ref={menuRef}>
          <button type="button" className={styles.overflowBtn} onClick={() => setMenuOpen((v) => !v)} aria-label="More actions">
            ⋯
          </button>
          {menuOpen && (
            <div className={styles.overflowMenu}>
              <button type="button" onClick={() => void downloadJson()}>Download submitted as JSON</button>
              <button type="button" className={styles.overflowDanger} disabled={busy === "reset"} onClick={() => void resetAll()}>
                Reset all to unapplied…
              </button>
            </div>
          )}
        </div>
      </div>

      {note && <div className={styles.empty} style={{ marginBottom: "0.75rem" }}>{note}</div>}

      {loading ? (
        <p className={styles.loadingText}>Loading applications…</p>
      ) : visible.length === 0 ? (
        <div className={styles.empty}>No applications match this filter.</div>
      ) : (
        <div className={styles.appGrid}>
          {visible.map((job) => {
            const sv = statusView(job.status);
            const score = typeof job.matchScore === "number" ? Math.round(job.matchScore) : null;
            const band = score != null ? matchBand(score) : null;
            return (
              <article key={job.id} className={styles.appCard} data-status={sv.key} data-job-id={job.id}>
                <div className={styles.appTop}>
                  <span className={styles.appCompany}>{job.company || "Unknown"}</span>
                  <span className={styles.statusBadge}>{sv.label}</span>
                </div>

                <button type="button" className={styles.appDetailsButton} onClick={() => setDetail(job)}>
                  {job.title || "Unknown role"}
                  <span className={styles.appDetailsHint}>View details ↗</span>
                </button>
                {job.location && <div className={styles.appLocation}>{job.location}</div>}

                {job.status === "INELIGIBLE" && (
                  <div className={styles.ineligibleReason}>
                    {INELIGIBILITY_LABELS[String(job.ineligibilityReason)] ||
                      job.ineligibilityDetail ||
                      "Cannot be applied to"}
                  </div>
                )}

                {score != null && band && (
                  <div className={styles.matchRow}>
                    <span className={styles.matchBadge} data-band={band.band}>
                      {score}% {band.label}
                    </span>
                    <span className={styles.matchTrack}>
                      <span className={styles.matchFill} style={{ width: `${Math.min(100, Math.max(0, score))}%` }} />
                    </span>
                  </div>
                )}

                {job.salary && <div className={styles.appLocation}>{job.salary}</div>}

                <div className={styles.appFoot}>
                  <span>
                    {job.status === "SUBMITTED" && job.submittedAt
                      ? `✓ Submitted ${relativeTime(job.submittedAt)}`
                      : relativeTime(job.updatedAt) || "—"}
                  </span>
                  {job.status === "QUEUED" || (job.status === "SKIPPED" && job.skipReason?.startsWith("Match score stayed below")) ? (
                    <button
                      type="button"
                      disabled={busy !== null}
                      className={styles.appFootLink}
                      onClick={() => void applyNow(job)}
                    >
                      {busy === job.id ? "Applying…" : "Apply →"}
                    </button>
                  ) : (
                    <button type="button" className={styles.appFootLink} onClick={() => setDetail(job)}>View →</button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <SidePanelPortal
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        panelClassName="aac-details-panel"
        backdropAriaLabel="Close application details"
      >
        {detail && (
          <div className="aa-wizard-panel-inner">
            <header className="aa-wizard-header">
              <div>
                <p className="aa-wizard-eyebrow">{statusView(detail.status).label}</p>
                <h2>{detail.company || "Unknown company"}</h2>
                <p className="aac-drawer-role">{detail.title}</p>
              </div>
              <button type="button" className="aa-wizard-close" aria-label="Close" onClick={() => setDetail(null)}>×</button>
            </header>

            <div className="aa-wizard-body aac-drawer-body">
              <section className="aac-drawer-section">
                <h4>Application</h4>
                <ul className="aac-drawer-stats aac-drawer-details">
                  {detail.location && <li>Location · {detail.location}</li>}
                  {typeof detail.matchScore === "number" && <li>Match · {Math.round(detail.matchScore)}%</li>}
                  {detail.resumeFileUsed && (
                    <li>
                      Resume ·{" "}
                      <a
                        href={`/api/backend/application-assistant/autopilot/jobs/${detail.id}/resume`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: "var(--accent)", textDecoration: "underline" }}
                      >
                        {detail.resumeFileUsed}
                      </a>
                    </li>
                  )}
                  {detail.submittedAt && <li>Submitted · {new Date(detail.submittedAt).toLocaleString()}</li>}
                  {detail.applicationUrl && (
                    <li>
                      Posting ·{" "}
                      <a href={detail.applicationUrl} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                        open
                      </a>
                    </li>
                  )}
                </ul>
              </section>

              {detail.lastError && (
                <section className="aac-drawer-section">
                  <h4>Why it stopped</h4>
                  <p style={{ margin: 0, fontSize: "12px", lineHeight: 1.5, color: "var(--text-secondary)" }}>
                    {detail.lastErrorType ? `[${detail.lastErrorType}] ` : ""}
                    {detail.lastError}
                  </p>
                </section>
              )}

              {detail.answers && Object.keys(detail.answers).length > 0 && (
                <section className="aac-drawer-section">
                  <h4>Answers submitted ({Object.keys(detail.answers).length})</h4>
                  <div style={{ maxHeight: 300, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
                    {Object.entries(detail.answers).map(([k, v]) => (
                      <div key={k} style={{ padding: "0.5rem 0.6rem", borderRadius: 8, background: "var(--bg-elevated)", border: "1px solid var(--border)" }}>
                        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text)" }}>{k}</div>
                        <div style={{ fontSize: 11, fontFamily: "monospace", color: "var(--accent)", wordBreak: "break-word" }}>
                          {String(v ?? "—")}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {(detail.checkpointHistory || []).length > 0 && (
                <section className="aac-drawer-section">
                  <h4>Pipeline history</h4>
                  <ul className="aac-drawer-stats aac-drawer-details">
                    {(detail.checkpointHistory || []).slice(-12).map((ck, i) => (
                      <li key={i}>
                        <strong>{ck.step}</strong>
                        {ck.details ? ` — ${String(ck.details).slice(0, 160)}` : ""}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          </div>
        )}
      </SidePanelPortal>
    </div>
  );
}
