"use client";

import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  approvePreflightSubmission,
  approveStagedAnswer,
  classifyPendingQuestions,
  getAutopilotJobs,
  skipStagedApplication,
} from "@/lib/application-assistant-api";
import { IconAlertCircle, IconBolt, IconCheckCircle } from "./icons";
import { ApplicationQueueCard, type QueueApplication } from "../application-queue-card";
import { resolveApplicationReadiness } from "../application-readiness";
import { QuickAddJobPanel } from "./quick-add-job-panel";

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

  const visibleJobs = jobs.filter((job) => {
    const role = roleFilter.trim().toLowerCase();
    const loc = locationFilter.trim().toLowerCase();
    const comp = companyFilter.trim().toLowerCase();
    if (role && !String(job.title || "").toLowerCase().includes(role)) return false;
    if (loc && !String(job.location || "").toLowerCase().includes(loc)) return false;
    if (comp && !String(job.company || "").toLowerCase().includes(comp)) return false;
    return true;
  });

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
      <div className="p-6 rounded-2xl border border-[#2ee8c9]/25 bg-gradient-to-br from-[#0a161f] via-[#0d1e2a] to-[#071017] shadow-xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <IconBolt className="w-5 h-5 text-[#2ee8c9]" />
            <span>Ready to Apply</span>
          </h2>
          <p className="text-xs text-slate-300 mt-1 max-w-2xl">
            Jobs that passed discovery's filters and ranking. Hit Apply — if something's unresolved, you'll be asked; otherwise it submits immediately.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="px-3.5 py-1 text-xs font-bold rounded-full bg-[#2ee8c9]/15 border border-[#2ee8c9]/40 text-[#2ee8c9]">
            {jobs.length} Ready
          </span>
          <button
            onClick={fetchAll}
            disabled={loading}
            className="px-3 py-1 text-xs font-semibold text-slate-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 transition-all cursor-pointer"
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </div>
      </div>

      <QuickAddJobPanel onAdded={fetchAll} />

      <div className="rounded-2xl border border-white/10 bg-[#0a101b] p-4 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold uppercase text-slate-500">Role</label>
          <input
            type="text"
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            placeholder="e.g. Software Engineer, Product Manager"
            className="w-56 rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold uppercase text-slate-500">Location</label>
          <input
            type="text"
            value={locationFilter}
            onChange={(e) => setLocationFilter(e.target.value)}
            placeholder="e.g. Remote, CA, United States"
            className="w-48 rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-bold uppercase text-slate-500">Company</label>
          <input
            type="text"
            value={companyFilter}
            onChange={(e) => setCompanyFilter(e.target.value)}
            placeholder="e.g. Stripe"
            className="w-40 rounded-lg border border-white/10 bg-black/30 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
          />
        </div>
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="px-3 py-1.5 text-xs font-semibold text-slate-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg border border-white/10 transition-all cursor-pointer"
          >
            Clear filters
          </button>
        )}
        <span className="ml-auto text-xs text-slate-500 self-center">
          Showing {visibleJobs.length} of {jobs.length}
        </span>
      </div>
      <p className="text-[11px] text-slate-500 -mt-3">
        Sponsorship isn't a per-listing filter — jobs that conflict with your work-authorization needs are already excluded at discovery (see the Skipped tab).
      </p>

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2">
          <IconCheckCircle className="w-4 h-4" />
          <span>{successMsg}</span>
        </div>
      )}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <IconAlertCircle className="w-4 h-4" />
          <span>{error}</span>
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          Nothing ready yet. Add a job by URL above, or find more from Job Discovery.
        </div>
      ) : visibleJobs.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No ready jobs match these filters.{" "}
          <button onClick={clearFilters} className="text-cyan-300 underline underline-offset-2 cursor-pointer">
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
                      <p className="aac-alert aac-alert--warn">
                        {questionsFor(job)[0]?.question || job.lastError || job.aiExplanation}
                      </p>
                    )}
                    <div className="flex items-center gap-1.5">
                      {(["off", "honest", "aggressive"] as TailoringMode[]).map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setModeByJob((prev) => ({ ...prev, [job.id]: m }));
                          }}
                          className={`px-2 py-1 rounded-md text-[10px] font-bold capitalize border transition-all cursor-pointer ${
                            mode === m
                              ? "bg-[#2ee8c9]/15 border-[#2ee8c9]/50 text-[#2ee8c9]"
                              : "bg-white/5 border-white/10 text-slate-400 hover:text-slate-200"
                          }`}
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
                      className="w-full rounded-xl bg-gradient-to-r from-emerald-500/25 via-teal-500/20 to-emerald-500/25 hover:from-emerald-500/35 hover:to-teal-500/35 text-emerald-200 border border-emerald-500/40 hover:border-emerald-400/60 py-2 px-3 font-bold text-xs transition flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
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

      {mounted && questionJob && createPortal(
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={() => setQuestionJob(null)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0a101b] p-6 space-y-4 shadow-2xl max-h-[85vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div>
              <h3 className="text-sm font-bold text-slate-100">{questionJob.company} — {questionJob.title}</h3>
              <p className="text-xs text-slate-400 mt-1">
                Before applying, {questionList.length > 1 ? "these need answers" : "this needs an answer"}:
              </p>
            </div>
            <div className="space-y-3">
              {questionList.map((q, i) => {
                const hasOptions = Array.isArray(q.options) && q.options.length > 0;
                return (
                  <div key={i} className="space-y-1.5">
                    <p className="text-sm text-slate-200 bg-white/5 border border-white/10 rounded-lg p-3">{q.question}</p>
                    {hasOptions ? (
                      <select
                        autoFocus={i === 0}
                        value={answerDrafts[i] || ""}
                        onChange={(e) =>
                          setAnswerDrafts((prev) => prev.map((v, idx) => (idx === i ? e.target.value : v)))
                        }
                        className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                      >
                        <option value="" className="bg-[#0a101b]">
                          Select...
                        </option>
                        {q.options!.map((opt) => (
                          <option key={opt} value={opt} className="bg-[#0a101b]">
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
                        className="w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus:border-cyan-400/50"
                      />
                    )}
                  </div>
                );
              })}
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setQuestionJob(null)}
                className="px-3.5 py-2 rounded-xl border border-white/10 bg-white/5 text-slate-300 text-xs font-semibold hover:bg-white/10 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleAnswerAndApply()}
                disabled={applyingId === questionJob.id}
                className="px-3.5 py-2 rounded-xl bg-emerald-500/25 border border-emerald-500/50 text-emerald-200 text-xs font-bold hover:bg-emerald-500/35 cursor-pointer disabled:opacity-50"
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
