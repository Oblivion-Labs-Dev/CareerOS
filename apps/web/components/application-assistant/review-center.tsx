"use client";

import React, { useEffect, useState } from "react";
import {
  approveStagedAnswer,
  getJobTailorDiff,
  getStagedApplications,
  openApplicationReview,
  reprocessStagedAutopilotJobs,
  reprocessSingleAutopilotJob,
  resetSingleAutopilotJob,
  skipStagedApplication,
  auditSponsorshipApplications,
  TailorDiffResponse,
} from "@/lib/application-assistant-api";
import { PreflightReviewModal } from "@/components/application-assistant/preflight-review-modal";
import { ApplicationQueueCard, type QueueApplication } from "@/components/application-assistant/application-queue-card";
import { resolveApplicationReadiness } from "@/components/application-assistant/application-readiness";

function fullReviewReason(job: any): { summary: string; blockingIssues: any[]; warnings: string[] } {
  const policy = job?.submissionEvidence?.policyEvaluation;
  const raw = String(job?.aiExplanation || job?.failureReason || "").replace(/^(Staged for human review:\s*)+/gi, "");
  const primaryQ = (job?.unresolvedQuestions || [])[0];
  const summary = raw || primaryQ?.question || "Review the prepared application before approval.";
  return {
    summary,
    blockingIssues: policy?.blockingIssues || [],
    warnings: policy?.warnings || [],
  };
}

export function ReviewCenter() {
  const [stagedList, setStagedList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editingAnswers, setEditingAnswers] = useState<Record<string, string>>({});
  const [answeringId, setAnsweringId] = useState<string | null>(null);
  const [diffModalData, setDiffModalData] = useState<TailorDiffResponse | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const fetchStaged = async () => {
    try {
      const res = await getStagedApplications();
      const list = res.staged || [];
      setStagedList(list);
      setSelectedId((prev) => (prev && list.some((j: any) => j.id === prev) ? prev : list[0]?.id ?? null));
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not fetch review applications");
    }
  };

  useEffect(() => {
    fetchStaged();
  }, []);

  const handleApprove = async (jobId: string, questionText: string) => {
    const answerToSubmit = editingAnswers[jobId]?.trim() || "";
    if (!answerToSubmit) {
      setError("Type an answer before saving — an empty answer won't be added to your answer library.");
      return;
    }
    setLoading(true);
    try {
      await approveStagedAnswer(jobId, questionText, answerToSubmit);
      setMessage(`Saved your answer for "${questionText}" — it'll be reused automatically next time this question comes up.`);
      setTimeout(() => setMessage(null), 4000);
      setAnsweringId(null);
      setEditingAnswers((prev) => {
        const next = { ...prev };
        delete next[jobId];
        return next;
      });
      await fetchStaged();
    } catch (err: any) {
      setError(err?.message || "Failed to approve answer");
    } finally {
      setLoading(false);
    }
  };

  const handleSkip = async (jobId: string) => {
    setLoading(true);
    try {
      await skipStagedApplication(jobId, "Skipped by candidate in Review Center");
      await fetchStaged();
    } catch (err: any) {
      setError(err?.message || "Failed to skip application");
    } finally {
      setLoading(false);
    }
  };

  const handleResetSingle = async (jobId: string) => {
    setLoading(true);
    try {
      await resetSingleAutopilotJob(jobId);
      setMessage("Application reset to unapplied");
      setTimeout(() => setMessage(null), 3500);
      await fetchStaged();
    } catch (err: any) {
      setError(err?.message || "Failed to reset application");
    } finally {
      setLoading(false);
    }
  };

  const handleRequeueAllStaged = async () => {
    setLoading(true);
    try {
      const res = await reprocessStagedAutopilotJobs();
      setMessage(res?.message || "Moved applications back to queue!");
      setTimeout(() => setMessage(null), 4000);
      await fetchStaged();
    } catch (err: any) {
      setError(err?.message || "Failed to requeue applications");
    } finally {
      setLoading(false);
    }
  };

  const handleAuditSponsorship = async () => {
    setLoading(true);
    try {
      const res = await auditSponsorshipApplications();
      setMessage(res?.message || `Audited applications: flagged ${res?.skippedCount ?? 0} jobs requiring US Citizenship`);
      setTimeout(() => setMessage(null), 5000);
      await fetchStaged();
    } catch (err: any) {
      setError(err?.message || "Failed to audit applications for US Citizenship & Sponsorship");
    } finally {
      setLoading(false);
    }
  };

  const handleCopyAllInReview = async () => {
    const prompt = [
      "Investigate and propose a safe fix for these CareerOS applications that are stuck in review.",
      "Do not submit any application. Diagnose why each one needed human review from the supplied evidence.",
      "",
      ...stagedList.map((job, index) => {
        const primaryQ = (job.unresolvedQuestions || [])[0] || {};
        return [
          `${index + 1}. ${job.company || "Unknown company"} — ${job.title || "Unknown role"}`,
          `Job URL: ${job.applicationUrl || job.listingUrl || "Not recorded"}`,
          `Job ID: ${job.id || job.jobId || "Not recorded"}`,
          `Blocking question: ${primaryQ.question || "Not recorded"}`,
          `Reason staged: ${job.failureReason || job.aiExplanation || "Not recorded"}`,
        ].join("\n");
      }),
    ].join("\n\n");

    try {
      await navigator.clipboard.writeText(prompt);
      setMessage(`Copied ${stagedList.length} in-review application${stagedList.length === 1 ? "" : "s"} as an AI-ready prompt.`);
      setTimeout(() => setMessage(null), 3000);
    } catch {
      setError("Could not copy the troubleshooting prompt. Please try again.");
    }
  };

  const handleQuickApply = async (job: any) => {
    setLoading(true);
    setError(null);
    const url = job.applicationUrl || job.listingUrl;
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    try {
      const sourceJobId = String(job.jobId || job.id || "");
      const appId = `app_${sourceJobId.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "")}`.slice(0, 120);
      
      const result = await openApplicationReview(appId, { force: true }).catch(() => null);
      if (result?.success) {
        setMessage(`Opened Chrome review window for "${job.title}". Form autofilled with saved profile data — review, correct any fields, and click Submit!`);
      } else if (url) {
        setMessage(`Opened "${job.title}" in a new browser tab.`);
      } else {
        throw new Error("No application URL available for this job.");
      }
      setTimeout(() => setMessage(null), 5000);
    } catch (err: any) {
      if (url) {
        setMessage(`Opened "${job.title}" in a new browser tab.`);
        setTimeout(() => setMessage(null), 3000);
      } else {
        setError(err?.message || "Could not open application URL");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleOpenDiff = async (job: any) => {
    setDiffLoading(true);
    setError(null);
    try {
      const res = await getJobTailorDiff(job.id);
      setDiffModalData(res.diff);
    } catch (err: any) {
      setError(err?.message || "Failed to load role tailoring diff");
    } finally {
      setDiffLoading(false);
    }
  };

  return (
    <div className="space-y-6 font-sans">
      {/* Header Banner */}
      <div className="p-6 rounded-2xl border border-amber-500/25 bg-gradient-to-br from-[#141009] via-[#1a140b] to-[#0c0a06] backdrop-blur-2xl shadow-xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <span>📋</span> Review & Pre-Flight Center
          </h2>
          <p className="text-xs text-slate-300 mt-1">
            Applications requiring review or pre-flight inspection. View live résumé diffs, verify tailored cover letters, and approve cloud submissions.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="px-3.5 py-1 text-xs font-bold rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.25)]">
            {stagedList.length} In Review
          </span>
          {stagedList.length > 0 && (
            <button
              onClick={handleCopyAllInReview}
              disabled={loading}
              className="px-3.5 py-1 text-xs font-bold text-violet-300 hover:text-violet-200 bg-violet-500/15 hover:bg-violet-500/25 rounded-xl border border-violet-500/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
              title="Copy every in-review question/reason as an AI-ready prompt"
            >
              📋 Copy all for LLM
            </button>
          )}
          <button
            onClick={handleAuditSponsorship}
            disabled={loading}
            className="px-3.5 py-1 text-xs font-bold text-amber-300 hover:text-amber-200 bg-amber-500/15 hover:bg-amber-500/25 rounded-xl border border-amber-500/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
            title="Audit and remove/skip applications requiring US Citizenship or ITAR clearance"
          >
            <span>🛡️</span> Filter Citizenship / ITAR
          </button>
          {stagedList.length > 0 && (
            <button
              onClick={handleRequeueAllStaged}
              disabled={loading}
              className="px-3.5 py-1 text-xs font-bold text-cyan-300 hover:text-cyan-200 bg-cyan-500/15 hover:bg-cyan-500/25 rounded-xl border border-cyan-500/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
              title="Move all in-review applications back to the Autopilot queue"
            >
              <span>⚡</span> Move All to Queue
            </button>
          )}
          <button
            onClick={fetchStaged}
            disabled={loading}
            className="px-3 py-1 text-xs font-semibold text-slate-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 transition-all cursor-pointer"
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </div>
      </div>

      {message && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2">
          <span>✓</span> {message}
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {stagedList.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No applications in review! All applications are processed automatically by Autopilot.
        </div>
      ) : (
        <div className="aa-queue-grid">
          {stagedList.map((job) => {
            const primaryQ = (job.unresolvedQuestions || [])[0] || {};
            const app: QueueApplication = { id: job.id, jobId: job.jobId || job.id, companyName: job.company || "Unknown company", roleTitle: job.title || "Unknown role", provider: job.provider || job.sourceProvider || "Autopilot", status: "in_review", progress: .7, verifiedCount: 0, reviewCount: 1, missingCount: 0, conflictingCount: 0, matchScore: job.matchScore, aiAnalyzed: job.matchScore != null, updatedAt: job.updatedAt || new Date().toISOString(), errors: [] };
            
            // Generate clean, readable summary instead of giant raw DOM error dumps
            const explanationSummary = (() => {
              if (job.failureReason) return job.failureReason;
              if (primaryQ.question) return primaryQ.question;
              if (job.aiExplanation) {
                const raw = String(job.aiExplanation).replace(/^(Staged for human review:\s*)+/gi, "");
                if (raw.includes("DOM Verification mismatch")) {
                  const matches = raw.match(/Required field '([^']+)'/g);
                  if (matches && matches.length > 0) {
                    const fields = matches.map(m => m.replace(/Required field '|'/g, "")).slice(0, 2);
                    return `Review required for: ${fields.join(", ")}${matches.length > 2 ? ` (+${matches.length - 2} more)` : ""}`;
                  }
                  return "Pre-flight verification requires human review before submit";
                }
                return raw.length > 90 ? `${raw.slice(0, 87)}…` : raw;
              }
              return "Review the prepared application before approval";
            })();

            const queueApp: QueueApplication = {
              ...app,
              hasSavedAutofillState: Object.keys(job.answers || {}).length > 0,
              quickApplyAvailable: true,
              autofillStepCount: Object.keys(job.answers || {}).length,
              quickApplyStepCount: Object.keys(job.answers || {}).length,
              quickApplyLabel: "Quick apply with saved answers",
              fields: Object.keys(job.answers || {}).map((label) => ({ label, classification: "verified" })),
            };
            const readiness = resolveApplicationReadiness(queueApp);

            const reviewDetails = fullReviewReason(job);

            return (
              <div
                key={job.id}
                onClick={() => setSelectedId(job.id)}
                className="cursor-pointer rounded-2xl transition"
              >
              <ApplicationQueueCard
                app={queueApp}
                statusAccent="amber"
                isOpening={false}
                isBrowserOpen={false}
                isAnalyzing={false}
                isWizardLoading={false}
                gateLoading={false}
                profileBlocked={false}
                readiness={readiness}
                needsAiAnalysis={false}
                pendingCount={0}
                isPreparing={false}
                isActivePrep={false}
                openingElapsedSec={0}
                analyzeElapsedSec={0}
                closingBrowser={false}
                onFocusBrowser={() => undefined}
                onResume={() => void handleQuickApply(job)}
                onAnswerQuestions={() => void handleQuickApply(job)}
                onOpenInBrowser={() => void handleQuickApply(job)}
                onToggleSubmitted={() => undefined}
                onArchive={() => void handleResetSingle(job.id)}
                primaryActionOverride={{
                  label: "⚡ Quick Apply",
                  onClick: () => void handleQuickApply(job),
                  disabled: loading,
                }}
                intelligenceSlot={
                  <div className="w-full flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleQuickApply(job);
                      }}
                      disabled={loading}
                      className="w-full rounded-xl bg-gradient-to-r from-amber-500/25 via-teal-500/20 to-amber-500/25 hover:from-amber-500/35 hover:to-teal-500/35 text-amber-200 border border-amber-500/40 hover:border-amber-400/60 py-2 px-3 font-semibold text-xs transition flex items-center justify-center gap-1.5 shadow-sm shadow-amber-950/40 cursor-pointer disabled:opacity-50"
                      title="Directly open application window to review and submit"
                    >
                      <span className="text-amber-300">⚡</span>
                      <span>Quick Apply in New Window</span>
                      <span className="text-amber-400 font-normal">→</span>
                    </button>
                  </div>
                }
                drawerContentSlot={
                  <div className="flex flex-col gap-4 mt-2">
                    <section className="aac-drawer-section">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="text-amber-300 font-semibold" style={{ margin: 0 }}>Why This Needs Review</h4>
                        <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300">
                          Pre-Flight Check
                        </span>
                      </div>
                      <p className="whitespace-pre-wrap leading-relaxed text-xs text-slate-200 bg-amber-500/[0.05] p-3 rounded-xl border border-amber-500/20">
                        {reviewDetails.summary}
                      </p>
                    </section>

                    {reviewDetails.blockingIssues.length > 0 && (
                      <section className="aac-drawer-section">
                        <h4 className="text-rose-300 font-semibold mb-2">
                          Blocking Issue{reviewDetails.blockingIssues.length === 1 ? "" : "s"} ({reviewDetails.blockingIssues.length})
                        </h4>
                        <ul className="flex flex-col gap-2">
                          {reviewDetails.blockingIssues.map((issue: any, i: number) => (
                            <li key={i} className="rounded-xl border border-rose-400/25 bg-rose-400/[0.08] p-3 text-xs">
                              <div className="font-semibold text-rose-200">{issue.question || issue.label || issue.gate}</div>
                              <div className="mt-1 text-slate-300">{issue.reason}</div>
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}

                    {reviewDetails.warnings.length > 0 && (
                      <section className="aac-drawer-section">
                        <h4 className="text-slate-400 font-semibold mb-1">Warnings</h4>
                        <ul className="flex flex-col gap-1 text-xs text-slate-400">
                          {reviewDetails.warnings.map((w: string, i: number) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className="text-amber-400">·</span> {w}
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}

                    {primaryQ.question && (
                      <section className="aac-drawer-section">
                        <h4 className="text-emerald-300 font-semibold mb-2">Answer & Learn for Future</h4>
                        <div className="flex flex-col gap-2 rounded-xl border border-emerald-400/25 bg-emerald-400/[0.06] p-3 text-xs">
                          <span className="font-medium text-emerald-100">
                            {primaryQ.question}
                          </span>
                          <div className="flex gap-2">
                            <input
                              type="text"
                              value={editingAnswers[job.id] || ""}
                              onChange={(e) => setEditingAnswers((prev) => ({ ...prev, [job.id]: e.target.value }))}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") void handleApprove(job.id, primaryQ.question || "");
                              }}
                              placeholder="Type the answer to save and reuse next time..."
                              className="flex-1 rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-slate-100 placeholder:text-slate-500 outline-none focus:border-emerald-400/50"
                            />
                            <button
                              type="button"
                              onClick={() => void handleApprove(job.id, primaryQ.question || "")}
                              disabled={loading || !(editingAnswers[job.id] || "").trim()}
                              className="rounded-lg bg-emerald-500/30 text-emerald-100 border border-emerald-500/50 hover:bg-emerald-500/45 px-3 py-2 font-semibold transition disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                            >
                              Save & Requeue
                            </button>
                          </div>
                        </div>
                      </section>
                    )}

                    <section className="aac-drawer-section flex flex-wrap gap-2 pt-2 border-t border-white/10">
                      <button
                        type="button"
                        onClick={() => void handleOpenDiff(job)}
                        disabled={loading || diffLoading}
                        className="rounded-xl bg-gradient-to-r from-cyan-500/20 to-teal-500/20 text-cyan-200 border border-cyan-400/40 hover:bg-cyan-500/30 px-4 py-2 font-bold transition flex items-center gap-1.5 shadow-sm disabled:opacity-50 cursor-pointer"
                        title="Open Tsenta 3-Way Resume Tailoring & Pre-flight Inspection"
                      >
                        🛠️ Pre-Flight Review (Tsenta Tailoring)
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleQuickApply(job)}
                        disabled={loading}
                        className="rounded-xl bg-gradient-to-r from-amber-500/30 to-teal-500/30 text-amber-200 border border-amber-500/50 hover:bg-amber-500/40 px-4 py-2 font-bold transition flex items-center gap-1.5 shadow-sm disabled:opacity-50 cursor-pointer"
                      >
                        ⚡ Quick Apply in New Window
                      </button>
                      {(job.applicationUrl || job.listingUrl) && (
                        <a
                          href={job.applicationUrl || job.listingUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded-xl border border-white/15 bg-white/[0.08] px-3.5 py-2 font-medium text-slate-200 transition hover:bg-white/[0.15]"
                        >
                          View Job Post ↗
                        </a>
                      )}
                      <button
                        type="button"
                        onClick={() => void reprocessSingleAutopilotJob(job.id).then(fetchStaged)}
                        disabled={loading}
                        className="rounded-xl bg-cyan-400/20 text-cyan-200 border border-cyan-400/30 px-3.5 py-2 font-medium transition hover:bg-cyan-400/30 disabled:opacity-50 cursor-pointer"
                      >
                        Move to Queue
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleSkip(job.id)}
                        disabled={loading}
                        className="rounded-xl bg-rose-500/20 text-rose-300 border border-rose-500/30 px-3.5 py-2 font-medium transition hover:bg-rose-500/30 disabled:opacity-50 cursor-pointer"
                      >
                        Skip
                      </button>
                    </section>
                  </div>
                }
              />
              </div>
            );
          })}
        </div>
      )}

      {/* Pre-Flight Review Modal */}
      {diffModalData && (
        <PreflightReviewModal
          diffData={diffModalData}
          onClose={() => setDiffModalData(null)}
          onSubmitted={() => {
            fetchStaged();
            setMessage("Pre-flight application approved and queued for cloud submission!");
            setTimeout(() => setMessage(null), 4000);
          }}
        />
      )}
    </div>
  );
}
