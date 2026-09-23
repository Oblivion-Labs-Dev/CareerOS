"use client";

import { transitionSurface } from "@/lib/surface-transition";
import { useApplicationScroll } from "@/hooks/use-application-scroll";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import { useSessionState } from "@/hooks/use-session-state";
import { useSearchParams } from "next/navigation";
import React, { useEffect, useRef, useState } from "react";
import { SidePanelPortal } from "@/components/side-panel-portal";
import { PendingQuestionAnswers, type QuestionGroupRow } from "./pending-question-answers";
import {
  assistedFillAutopilotJob,
  approvePreflightSubmission,
  approveStagedAnswer,
  setAutopilotJobState,
  reprocessSingleAutopilotJob,
  requeueBucket,
  skipStagedApplication,
} from "@/lib/application-assistant-api";
import type { AutopilotJobRow } from "./job-types";
import { FILTERS, SORTS, STATUS_VIEWS, SUBMITTED_DRILLDOWN, type StatusFilter, type SortMode } from "./job-presentation";
import { useApplicationPages } from "./use-application-pages";
import { ApplicationDetails } from "./application-details";
import detailStyles from "./application-details.module.css";
import { ApplicationCard } from "./application-card";
import { QuickAddJobPanel } from "./quick-add-job-panel";
import { CompanyFilterDropdown } from "./company-filter-dropdown";
import { TitleFilterDropdown } from "./title-filter-dropdown";
import styles from "./control-center.module.css";
import gridStyles from "./application-grid.module.css";

type RequeueBucket = "review" | "failed" | "manual" | "skipped" | "ineligible";
// Sweeping the whole bucket is only safe for review/failed - see the matching
// COMPANY_ONLY_BUCKETS guard in the backend's /autopilot/requeue-bucket.
const COMPANY_ONLY_BUCKETS = new Set<RequeueBucket>(["manual", "skipped", "ineligible"]);
const BUCKET_LABELS: Record<RequeueBucket, string> = {
  review: "in review",
  failed: "failed",
  manual: "manual review",
  skipped: "skipped",
  ineligible: "ineligible",
};

export function AutopilotApplicationsView({
  onJobsChanged,
  allJobs = [],
  questionGroups = [],
  onAnswered,
}: {
  onJobsChanged: () => void;
  allJobs?: AutopilotJobRow[];
  /** Outstanding questions, answerable under the Review filter. */
  questionGroups?: QuestionGroupRow[];
  onAnswered?: () => void;
}) {
  const params = useSearchParams();
  const linkedFilter = params.get("tab");
  const linkedJob = params.get("job");
  const [filter, setFilter] = useSessionState<StatusFilter>("applications-filter", FILTERS.some(item => item.id === linkedFilter) ? linkedFilter as StatusFilter : "all");
  const [sortMode, setSortMode] = useSessionState<SortMode>("applications-sort", "priority");
  const [companyFilter, setCompanyFilter] = useSessionState<string>("applications-company-filter", "");
  const [titleFilter, setTitleFilter] = useSessionState<string>("applications-title-filter", "");
  // Which ATS the application goes through, e.g. "workday" to work those by hand.
  const [atsFilter, setAtsFilter] = useSessionState<string>("applications-ats-filter", "");
  // Which bulk requeue is awaiting confirmation, if any. Held as state rather
  // than using window.confirm so the warning can say exactly what is about to
  // happen and how many rows it touches.
  // "Submitted" is the umbrella (open + rejected); its two children are shown
  // as a drill-down row once it (or one of them) is the active filter.
  const showSubmittedDrilldown = filter === "submitted" || filter === "open" || filter === "rejected";
  const [confirmRequeue, setConfirmRequeue] = useState<RequeueBucket | null>(null);
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
  const applyInFlight = useRef(false);

  useEffect(() => {
    if (FILTERS.some(item => item.id === linkedFilter)) setFilter(linkedFilter as StatusFilter);
  }, [linkedFilter]);

  const pages = useApplicationPages(filter, sortMode, "", companyFilter, titleFilter, atsFilter);
  const { jobs, counts, companyCounts: serverCompanyCounts, titleCounts: serverTitleCounts } = pages;

  // Use precomputed server company counts for the current status (covers all companies, e.g. all 152 on manual)
  const companyCounts = React.useMemo(() => {
    if (serverCompanyCounts && Object.keys(serverCompanyCounts).length > 0) {
      return serverCompanyCounts;
    }
    const map: Record<string, number> = {};
    const source = allJobs.length > 0 ? allJobs : jobs;

    const matching = source.filter((j) => {
      return FILTERS.find(item => item.id === filter)?.match(j) ?? true;
    });

    for (const j of matching) {
      const c = (j.company || "").trim();
      if (c) {
        map[c] = (map[c] || 0) + 1;
      }
    }
    return map;
  }, [serverCompanyCounts, allJobs, jobs, filter]);

  const sortedCompanies = React.useMemo(() => {
    return Object.entries(companyCounts).sort((a, b) => {
      if (b[1] !== a[1]) return b[1] - a[1];
      return a[0].localeCompare(b[0]);
    });
  }, [companyCounts]);

  // Use precomputed server title counts for the current status, same shape as companyCounts.
  const titleCounts = React.useMemo(() => {
    if (serverTitleCounts && Object.keys(serverTitleCounts).length > 0) {
      return serverTitleCounts;
    }
    const map: Record<string, number> = {};
    const source = allJobs.length > 0 ? allJobs : jobs;

    const matching = source.filter((j) => {
      return FILTERS.find(item => item.id === filter)?.match(j) ?? true;
    });

    for (const j of matching) {
      const t = (j.title || "").trim();
      if (t) {
        map[t] = (map[t] || 0) + 1;
      }
    }
    return map;
  }, [serverTitleCounts, allJobs, jobs, filter]);

  const sortedTitles = React.useMemo(() => {
    return Object.entries(titleCounts).sort((a, b) => {
      if (b[1] !== a[1]) return b[1] - a[1];
      return a[0].localeCompare(b[0]);
    });
  }, [titleCounts]);

  const totalStatusJobs = React.useMemo(() => {
    if (typeof counts[filter] === "number" && counts[filter] > 0) {
      return counts[filter];
    }
    return Object.values(companyCounts).reduce((sum, n) => sum + n, 0);
  }, [counts, filter, companyCounts]);

  // Reset company filter only if the chosen company definitely does not exist in the non-empty status list
  useEffect(() => {
    if (companyFilter && Object.keys(companyCounts).length > 0 && !companyCounts[companyFilter]) {
      setCompanyFilter("");
    }
  }, [companyCounts, companyFilter, setCompanyFilter]);

  // Same guard for the title filter — clear it if the selected title has no jobs left in this status.
  useEffect(() => {
    if (titleFilter && Object.keys(titleCounts).length > 0 && !titleCounts[titleFilter]) {
      setTitleFilter("");
    }
  }, [titleCounts, titleFilter, setTitleFilter]);

  // Most common ATS first; "other" (no recognised ATS) always last.
  const sortedAts = React.useMemo(
    () => Object.entries(pages.atsCounts).sort(([a, x], [b, y]) => Number(a === "other") - Number(b === "other") || y - x),
    [pages.atsCounts],
  );

  useEffect(() => {
    if (atsFilter && Object.keys(pages.atsCounts).length > 0 && !pages.atsCounts[atsFilter]) {
      setAtsFilter("");
    }
  }, [pages.atsCounts, atsFilter, setAtsFilter]);

  useApplicationScroll(`${filter}:${sortMode}:${companyFilter}:${titleFilter}:${atsFilter}`, pages.loading, pages.hasMore, jobs.length, pages.loadMore);

  const visible = React.useMemo(() => {
    let result = jobs;
    if (companyFilter) {
      result = result.filter((j) => (j.company || "").trim().toLowerCase() === companyFilter.trim().toLowerCase());
    }
    if (titleFilter) {
      result = result.filter((j) => (j.title || "").trim().toLowerCase() === titleFilter.trim().toLowerCase());
    }
    return result;
  }, [jobs, companyFilter, titleFilter]);

  const loading = pages.loading && jobs.length === 0;
  const pagination = <div ref={pages.sentinel} style={{ padding: "20px", textAlign: "center" }}>
    <p role="status">{pages.error || (pages.loading ? "Loading applications…" : `${jobs.length} of ${pages.total} applications`)}</p>
    {(pages.hasMore || pages.error) && <button className={styles.filterChip} disabled={pages.loading} onClick={pages.loadMore}>{pages.error ? "Retry" : "Load 24 more"}</button>}
  </div>;

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

  /** Send a bucket back to the queue - the whole thing for review/failed, or
   *  (required) just the current company filter's slice for manual/skipped/
   *  ineligible, so "requeue" from a filtered tab only touches what's shown. */
  const doRequeueBucket = async (bucket: RequeueBucket) => {
    setConfirmRequeue(null);
    setBusy("requeue");
    setNote(null);
    try {
      const res = await requeueBucket(bucket, companyFilter || undefined);
      setNote(res.message);
      pages.refresh();
      onJobsChanged();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not requeue those applications");
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

  return (
    <div>
      {/* Add Job by URL lived only on ApplyBoard, which the control-center
          redesign stopped rendering — so there was no way to queue a specific
          posting from the UI at all. */}
      <div style={{ marginBottom: "1rem" }}>
        <QuickAddJobPanel onAdded={() => { pages.refresh(); onJobsChanged(); }} />
      </div>

      <section className={gridStyles.controls} aria-label="Application filters">
        <div className={gridStyles.heading}><div><span className={gridStyles.eyebrow}>YOUR NEXT CHAPTER</span><h2>Application workspace</h2></div><span className={gridStyles.total}>{(counts.all ?? 0).toLocaleString()} applications</span></div>
        {/* Literal status names, not a "Needs you"/"In progress" grouping —
            every status is one click away, all the time. */}
        <nav className={gridStyles.views} aria-label="Application status">
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}><span>All applications</span><strong>{(counts.all ?? 0).toLocaleString()}</strong></button>
          {STATUS_VIEWS.map(id => {
            const item = FILTERS.find(f => f.id === id)!;
            const isActive = id === "submitted" ? showSubmittedDrilldown : filter === id;
            return (
              <button key={id} type="button" aria-pressed={isActive} data-view={id} onClick={() => setFilter(id)}>
                <span>{item.label}</span><strong>{(counts[id] ?? 0).toLocaleString()}</strong>
              </button>
            );
          })}
        </nav>
        {showSubmittedDrilldown && (
          <nav className={gridStyles.drilldown} aria-label="Submitted breakdown">
            {SUBMITTED_DRILLDOWN.map(id => {
              const item = FILTERS.find(f => f.id === id)!;
              return (
                <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}>
                  {item.label} <strong>{(counts[id] ?? 0).toLocaleString()}</strong>
                </button>
              );
            })}
          </nav>
        )}
      {/* Always visible: the filters are how these lists get worked through, so
          they are not tucked behind a toggle. Free-text search was removed as
          unused (repo owner, 2026-09-23); add it back if a need shows up. */}
      <div id="application-extra-filters" className={gridStyles.extraFilters}>
        <CompanyFilterDropdown
          value={companyFilter}
          onChange={setCompanyFilter}
          companies={sortedCompanies}
          totalCount={totalStatusJobs}
        />

        <TitleFilterDropdown
          value={titleFilter}
          onChange={setTitleFilter}
          titles={sortedTitles}
          totalCount={totalStatusJobs}
        />

        <select
          className={styles.searchInput}
          style={{ maxWidth: "13rem", cursor: "pointer" }}
          value={atsFilter}
          onChange={(e) => setAtsFilter(e.target.value)}
          aria-label="Filter by application system"
        >
          <option value="">All application systems</option>
          {sortedAts.map(([id, count]) => (
            <option key={id} value={id}>{pages.atsLabels[id] || id} ({count.toLocaleString()})</option>
          ))}
        </select>

        <select
          className={styles.searchInput}
          style={{ maxWidth: "13rem", cursor: "pointer" }}
          value={sortMode}
          onChange={(e) => setSortMode(e.target.value as SortMode)}
          aria-label="Sort applications"
        >
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>

        {(() => {
          if (!(filter === "review" || filter === "failed" || filter === "manual" || filter === "skipped" || filter === "ineligible")) {
            return null;
          }
          const bucket = filter as RequeueBucket;
          // Manual/skipped/ineligible were deliberately never bulk-requeueable
          // wholesale - those buckets are what the user has already worked
          // through and dismissed. A company filter turns this into a
          // different, deliberate action ("the Roblox fix landed, send just
          // Roblox's back"), so the button only appears for them once a
          // company is chosen - mirrors the backend's COMPANY_ONLY_BUCKETS guard.
          if (COMPANY_ONLY_BUCKETS.has(bucket) && !companyFilter) return null;
          const scopedCount = companyFilter ? (companyCounts[companyFilter] ?? 0) : (counts[filter] ?? 0);
          if (scopedCount <= 0) return null;
          return (
            <button
              type="button"
              className={styles.filterChip}
              disabled={busy === "requeue"}
              onClick={() => setConfirmRequeue(bucket)}
            >
              {busy === "requeue"
                ? "Moving…"
                : companyFilter
                  ? `Move ${scopedCount} ${companyFilter} to queue`
                  : `Move all ${scopedCount} to queue`}
            </button>
          );
        })()}

      </div>

      </section>

      {/* The questions holding these applications, answerable in place.
          Below the filter bar and above the cards: the user comes to Review to
          clear blockers, and one answer here can finish dozens of the cards
          underneath it. Only under this filter — it is not relevant to
          submitted or ineligible work. */}
      {filter === "review" && questionGroups.length > 0 && (
        <PendingQuestionAnswers
          groups={questionGroups}
          onAnswered={() => {
            // Answering requeues applications; this list keeps its own page
            // cache, so without this they stayed on screen under Review.
            pages.refresh();
            onAnswered?.();
          }}
        />
      )}

      {confirmRequeue && (
        <div className={styles.confirmBackdrop} role="presentation" onClick={() => setConfirmRequeue(null)}>
          <div
            className={styles.confirmCard}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="requeue-confirm-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 id="requeue-confirm-title" className={styles.confirmTitle}>
              Move {companyFilter ? (companyCounts[companyFilter] ?? 0) : (counts[confirmRequeue] ?? 0)}{" "}
              {companyFilter ? `${companyFilter} ` : "all "}
              {BUCKET_LABELS[confirmRequeue]} application{(companyFilter ? (companyCounts[companyFilter] ?? 0) : (counts[confirmRequeue] ?? 0)) === 1 ? "" : "s"} back to the queue?
            </h3>
            <p className={styles.confirmBody}>
              Autopilot will try each of them again. The reason each one was set aside — the
              question that still needed answering, the error that broke the attempt, or the
              ineligibility verdict — is cleared so it can be retried.
            </p>
            <p className={styles.confirmWarning}>This cannot be undone.</p>
            <div className={styles.confirmActions}>
              <button type="button" className={styles.filterChip} onClick={() => setConfirmRequeue(null)}>
                Cancel
              </button>
              <button
                type="button"
                className={styles.confirmDanger}
                onClick={() => void doRequeueBucket(confirmRequeue)}
              >
                Yes, move them to the queue
              </button>
            </div>
          </div>
        </div>
      )}

      {note && <div className={styles.empty} style={{ marginBottom: "0.75rem" }}>{note}</div>}

      {loading ? (
        <WorkspaceLoading label="Loading applications…" shape="grid" rows={6} />
      ) : visible.length === 0 ? (
        <div className={styles.empty}>No applications match this filter.</div>
      ) : (
        <div className={gridStyles.grid} aria-label="Applications">
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
