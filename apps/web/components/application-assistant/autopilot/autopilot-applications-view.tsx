"use client";

import { transitionSurface } from "@/lib/surface-transition";
import { useApplicationScroll } from "@/hooks/use-application-scroll";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import { useSessionState } from "@/hooks/use-session-state";
import { useSearchParams } from "next/navigation";
import React, { useEffect, useRef, useState } from "react";
import { SidePanelPortal } from "@/components/side-panel-portal";
import {
  assistedFillAutopilotJob,
  approvePreflightSubmission,
  approveStagedAnswer,
  getAutopilotJobs,
  setAutopilotJobState,
  reprocessSingleAutopilotJob,
  resetSubmittedAutopilotJobs,
  skipStagedApplication,
} from "@/lib/application-assistant-api";
import { LatencyDiagnosticsCenter } from "@/components/application-assistant/latency-diagnostics-center";
import type { AutopilotJobRow } from "./job-types";
import { FILTERS, SORTS, type StatusFilter, type SortMode } from "./job-presentation";
import { useApplicationPages } from "./use-application-pages";
import { ApplicationDetails } from "./application-details";
import detailStyles from "./application-details.module.css";
import { ApplicationCard } from "./application-card";
import { QuickAddJobPanel } from "./quick-add-job-panel";
import styles from "./control-center.module.css";

type Section = "applications" | "review" | "diagnostics";
export function AutopilotApplicationsView({
  section,
  onJobsChanged,
}: {
  section: Section;
  onJobsChanged: () => void;
}) {
  const params = useSearchParams();
  const linkedFilter = params.get("tab");
  const linkedJob = params.get("job");
  const [filter, setFilter] = useSessionState<StatusFilter>("applications-filter", FILTERS.some(item => item.id === linkedFilter) ? linkedFilter as StatusFilter : "all");
  const [sortMode, setSortMode] = useSessionState<SortMode>("applications-sort", "priority");
  const [query, setQuery] = useSessionState("applications-query", "");
  const [menuOpen, setMenuOpen] = useState(false);
  const [detail, setDetail] = useState<AutopilotJobRow | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [answerDrafts, setAnswerDrafts] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!linkedJob) return;
    const controller = new AbortController();
    fetch(`/api/backend/application-assistant/autopilot/jobs/${encodeURIComponent(linkedJob)}`, {signal: controller.signal})
      .then(async response => {if (!response.ok) throw new Error(); return response.json();})
      .then(value => setDetail(value.job))
      .catch(() => {if (!controller.signal.aborted) setNote("This application could not be opened. Try finding it in the list.");});
    return () => controller.abort();
  }, [linkedJob]);
  const menuRef = useRef<HTMLDivElement>(null);
  const applyInFlight = useRef(false);

  useEffect(() => {
    if (section === "review") setFilter("review");
    else if (section === "diagnostics") setFilter("failed");
    else if (FILTERS.some(item => item.id === linkedFilter)) setFilter(linkedFilter as StatusFilter);
  }, [section, linkedFilter]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [menuOpen]);

  const pages = useApplicationPages(section === "review" ? "review" : filter, sortMode, query);
  const { jobs, counts } = pages;
  useApplicationScroll(`${section}:${filter}:${sortMode}:${query}`, pages.loading, pages.hasMore, jobs.length, pages.loadMore);
  const visible = jobs;
  const loading = pages.loading && jobs.length === 0;
  const pagination = <div ref={pages.sentinel} style={{ padding: "20px", textAlign: "center" }}>
    <p role="status">{pages.error || (pages.loading ? "Loading applications…" : `${jobs.length} of ${pages.total} applications`)}</p>
    {(pages.hasMore || pages.error) && <button className={styles.filterChip} disabled={pages.loading} onClick={pages.loadMore}>{pages.error ? "Retry" : "Load 20 more"}</button>}
  </div>;

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
      "Reset staged, failed and in-flight jobs back to unapplied?" +
      "\n\nSubmitted, skipped and ineligible applications are left alone. This cannot be undone.",
    );
    if (!confirmed) return;
    setBusy("reset");
    try {
      await resetSubmittedAutopilotJobs("ALL");
      setNote("Reset complete.");
      pages.refresh();
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
      await approvePreflightSubmission(job.id);
      setNote(`Approved — applying to ${job.company}.`);
      setDetail(null);
      pages.refresh();
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
      // No tailoring mode is passed: clicking Apply must honour whatever mode
      // the job (or the global Autopilot setting) already has. Hardcoding
      // "honest" here silently overrode a global "off" and made every
      // application re-tailor the resume through the local LLM.
      const res = await approvePreflightSubmission(job.id);
      setNote(res?.message || `Applying to ${job.company} — this can take a minute.`);
      pages.refresh();
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Failed to apply");
    } finally {
      applyInFlight.current = false;
      setBusy(null);
    }
  };

  /**
   * Re-run a failed application. The job has to go back through reprocess
   * before it can be approved again — a FAILED job is not in the queue, so
   * approving it on its own would do nothing.
   */
  const retryNow = async (job: AutopilotJobRow) => {
    if (applyInFlight.current || job.status !== "FAILED") return;
    applyInFlight.current = true;
    setBusy(job.id);
    setNote(null);
    try {
      await reprocessSingleAutopilotJob(job.id);
      const res = await approvePreflightSubmission(job.id);
      setNote(res?.message || `Retrying ${job.company} — this can take a minute.`);
      pages.refresh();
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not retry this application");
    } finally {
      applyInFlight.current = false;
      setBusy(null);
    }
  };

  /** Fill the form in a visible browser and hand it over for the user to finish. */
  const assistedFill = async (job: AutopilotJobRow) => {
    setBusy(job.id);
    setNote(`Opening ${job.company} and filling what we can…`);
    try {
      const res = await assistedFillAutopilotJob(job.id);
      setNote(res?.message || `Filled the ${job.company} form — finish it in the browser window.`);
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not open this application");
    } finally {
      setBusy(null);
    }
  };

  // The user is the one looking at the posting, so they decide which bucket it
  // belongs in — including the common case of a link that turns out to be dead.
  const setJobState = async (job: AutopilotJobRow, status: string, label: string) => {
    setBusy(job.id);
    setNote(null);
    try {
      const res = await setAutopilotJobState(job.id, status);
      setNote(`${job.company || "Application"} set to ${label}.`);
      setDetail((current) => (current && current.id === job.id ? { ...current, ...res.job } : current));
      pages.refresh();
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not update this application");
    } finally {
      setBusy(null);
    }
  };

  const skipJob = async (job: AutopilotJobRow) => {
    setBusy(job.id);
    try {
      await skipStagedApplication(job.id, "Skipped from Autopilot review");
      setNote(`Skipped ${job.company}.`);
      setDetail(null);
      pages.refresh();
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
        {pagination}
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

      {/* Add Job by URL lived only on ApplyBoard, which the control-center
          redesign stopped rendering — so there was no way to queue a specific
          posting from the UI at all. */}
      {section === "applications" && (
        <div style={{ marginBottom: "1rem" }}>
          <QuickAddJobPanel onAdded={() => { pages.refresh(); onJobsChanged(); }} />
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
        <WorkspaceLoading label="Loading applications…" />
      ) : visible.length === 0 ? (
        <div className={styles.empty}>No applications match this filter.</div>
      ) : (
        <div className={styles.appGrid}>
          {visible.map((job) => (
            <ApplicationCard key={job.id} job={job} busy={busy} detailed={detail?.id === job.id}
              onDetails={() => transitionSurface(() => setDetail(job))} onApply={() => void applyNow(job)}
              onAssistedFill={() => void assistedFill(job)}
              onRetry={() => void retryNow(job)} />
          ))}
        </div>
      )}

      {pagination}
      <SidePanelPortal
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        panelClassName={detailStyles.panel}
        ariaLabelledBy="application-details-title"
        backdropAriaLabel="Close application details"
      >
        {detail && (
          <ApplicationDetails
            job={detail}
            onClose={() => setDetail(null)}
            answerDrafts={answerDrafts}
            onDraftChange={(question, value) =>
              setAnswerDrafts((prev) => ({ ...prev, [`${detail.id}:${question}`]: value }))
            }
            onApprove={() => void approveAnswers(detail)}
            onSkip={() => void skipJob(detail)}
            onSetState={(status, label) => void setJobState(detail, status, label)}
            busy={busy === detail.id}
          />
        )}
      </SidePanelPortal>
    </div>
  );
}
