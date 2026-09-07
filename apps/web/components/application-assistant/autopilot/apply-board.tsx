"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  approvePreflightSubmission,
  approveStagedAnswer,
  classifyPendingQuestions,
  getAutopilotJobs,
  skipStagedApplication,
} from "@/lib/application-assistant-api";
import { IconAlertCircle, IconBolt, IconCheckCircle, IconRefresh } from "./icons";
import { ApplicationQueueCard, type QueueApplication } from "../application-queue-card";
import { resolveApplicationReadiness } from "../application-readiness";
import { QuickAddJobPanel } from "./quick-add-job-panel";
import styles from "./autopilot-ui.module.css";

const PAGE_SIZE = 10;

type TailoringMode = "off" | "honest" | "aggressive";

type PendingQuestion = { question: string; rawLabel?: string; fieldType?: string; options?: string[] };

// The backend records the outstanding question(s) as one semicolon-joined
// string (radio/checkbox groups can also produce the same underlying question
// more than once). Split and dedupe so the UI shows each distinct question once.
function splitReasons(text: string): string[] {
  const withoutPrefix = text.replace(/^Staged for human review:\s*/i, "");
  const parts = withoutPrefix
    .split(";")
    .map((p) => p.trim())
    .filter(Boolean);
  return Array.from(new Set(parts));
}

// Newer jobs carry structured pendingQuestions (with field type + real dropdown
// options straight from the live DOM); older ones only have the raw error text.
// Prefer the structured form so a select field renders as a dropdown with its
// actual choices instead of a blind text box.
function questionsFor(job: any): PendingQuestion[] {
  if (Array.isArray(job.pendingQuestions) && job.pendingQuestions.length > 0) {
    return job.pendingQuestions;
  }
  const raw = job.lastError || job.aiExplanation || "";
  return splitReasons(raw).map((question) => ({ question }));
}

/**
 * The Autopilot page's primary view: every job that has cleared discovery's hard
 * filters and ranking sits here as a ready-to-apply card. There is no separate
 * "Start Run" step — clicking Apply on a card either applies immediately (nothing
 * unresolved) or asks the one outstanding question first, then applies.
 */
export function ApplyBoard() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [classifyingId, setClassifyingId] = useState<string | null>(null);
  const [questionJob, setQuestionJob] = useState<any | null>(null);
  const [questionList, setQuestionList] = useState<PendingQuestion[]>([]);
  const [answerDrafts, setAnswerDrafts] = useState<string[]>([]);
  const [modeByJob, setModeByJob] = useState<Record<string, TailoringMode>>({});
  const [roleFilter, setRoleFilter] = useState("");
  const [locationFilter, setLocationFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [mounted, setMounted] = useState(false);
  // The 3 merged statuses are fetched in full (needed so text filters search
  // across everything, not just whatever's been scrolled into view) — only
  // rendering is paginated, revealing PAGE_SIZE more rows at a time.
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [queued, needsReview, staged] = await Promise.all([
        getAutopilotJobs("QUEUED").catch(() => ({ jobs: [] })),
        getAutopilotJobs("NEEDS_REVIEW").catch(() => ({ jobs: [] })),
        getAutopilotJobs("STAGED").catch(() => ({ jobs: [] })),
      ]);
      const merged = [...(queued.jobs || []), ...(needsReview.jobs || []), ...(staged.jobs || [])];
      merged.sort((a, b) => (b.matchScore ?? 0) - (a.matchScore ?? 0));
      setJobs(merged);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not load the apply queue");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 5000);
    return () => clearInterval(interval);
  }, []);

  const modeFor = (job: any): TailoringMode => modeByJob[job.id] || job.tailoringMode || "honest";

  const filteredJobs = jobs.filter((job) => {
    const role = roleFilter.trim().toLowerCase();
    const loc = locationFilter.trim().toLowerCase();
    const comp = companyFilter.trim().toLowerCase();
    if (role && !String(job.title || "").toLowerCase().includes(role)) return false;
    if (loc && !String(job.location || "").toLowerCase().includes(loc)) return false;
    if (comp && !String(job.company || "").toLowerCase().includes(comp)) return false;
    return true;
  });
  const visibleJobs = filteredJobs.slice(0, visibleCount);
  const hasMoreVisible = visibleCount < filteredJobs.length;

  // Filters (and the underlying job list) narrow or widen what's on offer —
  // restart pagination from the top rather than showing a stale, possibly
  // now-too-large slice.
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [roleFilter, locationFilter, companyFilter]);

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setVisibleCount((prev) => Math.min(prev + PAGE_SIZE, filteredJobs.length));
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [filteredJobs.length]);

  const hasActiveFilters = Boolean(roleFilter || locationFilter || companyFilter);
  const clearFilters = () => {
    setRoleFilter("");
    setLocationFilter("");
    setCompanyFilter("");
  };

  const doApply = async (job: any, answers?: Record<string, string>) => {
    setApplyingId(job.id);
    setError(null);
    try {
      const res = await approvePreflightSubmission(job.id, answers, modeFor(job));
      setSuccessMsg(res.message || `Applying to "${job.title}" now — check the Submitted tab shortly.`);
      setTimeout(() => setSuccessMsg(null), 4000);
      await fetchAll();
    } catch (err: any) {
      setError(err?.message || "Failed to apply");
    } finally {
      setApplyingId(null);
    }
  };

  const openQuestionModal = (job: any, questions: PendingQuestion[]) => {
    setQuestionJob(job);
    setQuestionList(questions);
    setAnswerDrafts(questions.map(() => ""));
  };

  const handleApplyClick = async (job: any) => {
    const needsAnswer = job.status === "NEEDS_REVIEW" || job.status === "STAGED";
    if (!needsAnswer) {
      void doApply(job);
      return;
    }

    const hasStructuredQuestions = Array.isArray(job.pendingQuestions) && job.pendingQuestions.length > 0;
    if (hasStructuredQuestions) {
      openQuestionModal(job, questionsFor(job));
      return;
    }

    // Older jobs staged before structured pendingQuestions existed only have raw
    // DOM-verification text on file — ask the model to clean that up into real
    // questions on demand rather than re-running the whole live submission.
    setClassifyingId(job.id);
    setError(null);
    try {
      const res = await classifyPendingQuestions(job.id);
      const questions = res.pendingQuestions || [];
      if (questions.length > 0) {
        openQuestionModal({ ...job, pendingQuestions: questions }, questions);
      } else {
        void doApply(job);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to prepare questions for this job");
    } finally {
      setClassifyingId(null);
    }
  };

  const handleAnswerAndApply = async () => {
    if (!questionJob) return;
    const pairs = questionList
      // Save keyed by the raw DOM label (stable across retries), not the
      // model's rephrased question text (varies call to call) — see
      // error_normalizer.build_pending_questions for why.
      .map((q, i) => ({ question: q.rawLabel || q.question, answer: answerDrafts[i]?.trim() || "" }))
      .filter((p) => p.answer);
    if (pairs.length === 0) {
      setError("Enter at least one answer before applying.");
      return;
    }
    setApplyingId(questionJob.id);
    setError(null);
    try {
      for (const { question, answer } of pairs) {
        await approveStagedAnswer(questionJob.id, question, answer);
      }
      await doApply(questionJob);
      setQuestionJob(null);
    } catch (err: any) {
      setError(err?.message || "Failed to save the answer");
    } finally {
      setApplyingId(null);
    }
  };

  const handleSkip = async (job: any) => {
    setError(null);
    try {
      await skipStagedApplication(job.id, "Skipped from Autopilot board");
      await fetchAll();
    } catch (err: any) {
      setError(err?.message || "Failed to skip");
    }
  };

  return (
    <div className="space-y-6 font-sans">
      <div className={styles.pageHeader}>
        <div>
          <h2 className={styles.pageTitle}>
            <IconBolt className={`w-5 h-5 ${styles.pageTitleIcon}`} />
            <span>Ready to Apply</span>
          </h2>
          <p className={styles.pageSubtitle}>
            Jobs that passed discovery's filters and ranking. Hit Apply — if something's unresolved, you'll be asked; otherwise it submits immediately.
          </p>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.badgeAccent}>{jobs.length} Ready</span>
          <button onClick={fetchAll} disabled={loading} className={styles.btnGhost}>
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </div>
      </div>

      <QuickAddJobPanel onAdded={fetchAll} />

      <div className={styles.filterBar}>
        <div className={styles.filterField}>
          <label className={styles.filterLabel}>Role</label>
          <input
            type="text"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            placeholder="e.g. Software Engineer, Product Manager"
            className={styles.filterInput}
          />
        </div>
        <div className={styles.filterField}>
          <label className={styles.filterLabel}>Location</label>
          <input
            type="text"
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
            placeholder="e.g. Remote, CA, United States"
            className={`${styles.filterInput} ${styles.filterInputNarrow}`}
          />
        </div>
        <div className={styles.filterField}>
          <label className={styles.filterLabel}>Company</label>
          <input
            type="text"
            value={companyFilter}
            onChange={(e) => setCompanyFilter(e.target.value)}
            placeholder="e.g. Stripe"
            className={`${styles.filterInput} ${styles.filterInputCompact}`}
          />
        </div>
        {hasActiveFilters && (
          <button onClick={clearFilters} className={styles.filterClear}>
            Clear filters
          </button>
        )}
        <span className={styles.filterCount}>
          Showing {visibleJobs.length} of {filteredJobs.length}{hasActiveFilters ? ` (${jobs.length} total)` : ""}
        </span>
      </div>
      <p className={styles.filterHint}>
        Sponsorship isn't a per-listing filter — jobs that conflict with your work-authorization needs are already excluded at discovery (see the Skipped tab).
      </p>

      {successMsg && (
        <div className={styles.alertSuccess}>
          <IconCheckCircle className="w-4 h-4" />
          <span>{successMsg}</span>
        </div>
      )}
      {error && (
        <div className={styles.alertError}>
          <IconAlertCircle className="w-4 h-4" />
          <span>{error}</span>
        </div>
      )}

      {jobs.length === 0 ? (
        <div className={styles.emptyState}>
          Nothing ready yet. Add a job by URL above, or find more from Job Discovery.
        </div>
      ) : visibleJobs.length === 0 ? (
        <div className={styles.emptyState}>
          No ready jobs match these filters.{" "}
          <button onClick={clearFilters} className={styles.emptyStateLink}>
            Clear filters
          </button>
        </div>
      ) : (
        <div className="aa-queue-grid">
          {visibleJobs.map((job) => {
            const needsAnswer = (job.status === "NEEDS_REVIEW" || job.status === "STAGED") && (job.lastError || job.aiExplanation);
            const mode = modeFor(job);
            const app: QueueApplication = {
              id: job.id,
              jobId: job.jobId || job.id,
              companyName: job.company || "Unknown company",
              roleTitle: job.title || "Unknown role",
              jobLocation: job.location || "",
              provider: job.provider || job.sourceProvider || "Autopilot",
              status: needsAnswer ? "needs_review" : "ready_to_prepare",
              progress: needsAnswer ? 0.6 : 0.9,
              verifiedCount: Object.keys(job.answers || {}).length,
              reviewCount: needsAnswer ? 1 : 0,
              missingCount: 0,
              conflictingCount: 0,
              matchScore: job.matchScore,
              aiAnalyzed: job.matchScore != null,
              updatedAt: job.updatedAt || job.queuedAt || new Date().toISOString(),
              errors: [],
              fields: Object.keys(job.answers || {}).map((label) => ({ label, classification: "verified" })),
            };

            return (
              <ApplicationQueueCard
                key={job.id}
                app={app}
                statusAccent={needsAnswer ? "purple" : "emerald"}
                isOpening={false}
                isBrowserOpen={false}
                isAnalyzing={false}
                isWizardLoading={false}
                gateLoading={false}
                profileBlocked={false}
                readiness={resolveApplicationReadiness(app)}
                needsAiAnalysis={false}
                pendingCount={0}
                isPreparing={applyingId === job.id || classifyingId === job.id}
                isActivePrep={false}
                openingElapsedSec={0}
                analyzeElapsedSec={0}
                closingBrowser={false}
                onFocusBrowser={() => undefined}
                onResume={() => void handleApplyClick(job)}
                onAnswerQuestions={() => void handleApplyClick(job)}
                onOpenInBrowser={() => undefined}
                onToggleSubmitted={() => undefined}
                onArchive={() => void handleSkip(job)}
                intelligenceSlot={
                  <div className="w-full space-y-2.5">
                    {needsAnswer && (
                      <p className={styles.readyAlertWarn}>
                        {questionsFor(job)[0]?.question || job.lastError || job.aiExplanation}
                      </p>
                    )}
                    <div className={styles.modeToggleGroup}>
                      {(["off", "honest", "aggressive"] as TailoringMode[]).map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setModeByJob((prev) => ({ ...prev, [job.id]: m }));
                          }}
                          className={`${styles.modeToggle} ${mode === m ? styles.modeToggleActive : ""}`}
                        >
                          {m}
                        </button>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleApplyClick(job);
                      }}
                      disabled={applyingId === job.id || classifyingId === job.id}
                      className={styles.applyCta}
                    >
                      {applyingId === job.id
                        ? "Applying..."
                        : classifyingId === job.id
                        ? "Preparing questions..."
                        : needsAnswer
                        ? "Answer & Apply"
                        : "⚡ Apply"}
                    </button>
                  </div>
                }
                primaryActionOverride={{
                  label:
                    applyingId === job.id
                      ? "Applying..."
                      : classifyingId === job.id
                      ? "Preparing..."
                      : needsAnswer
                      ? "Answer & Apply"
                      : "Apply",
                  onClick: () => void handleApplyClick(job),
                  disabled: applyingId === job.id || classifyingId === job.id,
                }}
              />
            );
          })}
        </div>
      )}

      {visibleJobs.length > 0 && hasMoreVisible && (
        <div ref={sentinelRef} className={styles.loadingMore}>
          <IconRefresh className={`w-4 h-4 ${styles.spin}`} />
          <span>Loading more applications...</span>
        </div>
      )}

      {mounted && questionJob && createPortal(
        <div className={styles.modalOverlay} onClick={() => setQuestionJob(null)}>
          <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
            <div>
              <h3 className={styles.modalTitle}>{questionJob.company} — {questionJob.title}</h3>
              <p className={styles.modalSubtitle}>
                Before applying, {questionList.length > 1 ? "these need answers" : "this needs an answer"}:
              </p>
            </div>
            <div className="space-y-3">
              {questionList.map((q, i) => {
                const hasOptions = Array.isArray(q.options) && q.options.length > 0;
                return (
                  <div key={i} className="space-y-1.5">
                    <p className={styles.questionBox}>{q.question}</p>
                    {hasOptions ? (
                      <select
                        autoFocus={i === 0}
                        value={answerDrafts[i] || ""}
                        onChange={(e) =>
                          setAnswerDrafts((prev) => prev.map((v, idx) => (idx === i ? e.target.value : v)))
                        }
                        className={styles.modalInput}
                      >
                        <option value="">Select...</option>
                        {q.options!.map((opt) => (
                          <option key={opt} value={opt}>
                            {opt}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        autoFocus={i === 0}
                        value={answerDrafts[i] || ""}
                        onChange={(e) =>
                          setAnswerDrafts((prev) => prev.map((v, idx) => (idx === i ? e.target.value : v)))
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void handleAnswerAndApply();
                        }}
                        placeholder="Your answer..."
                        className={styles.modalInput}
                      />
                    )}
                  </div>
                );
              })}
            </div>
            <div className={styles.modalActions}>
              <button type="button" onClick={() => setQuestionJob(null)} className={styles.modalBtnCancel}>
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleAnswerAndApply()}
                disabled={applyingId === questionJob.id}
                className={styles.modalBtnSave}
              >
                {applyingId === questionJob.id ? "Applying..." : "Save & Apply"}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}
