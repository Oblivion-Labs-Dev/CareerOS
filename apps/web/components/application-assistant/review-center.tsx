"use client";

import React, { useEffect, useState } from "react";
import {
  approveStagedAnswer,
  getJobTailorDiff,
  getStagedApplications,
  openApplicationReview,
  reprocessFailedAutopilotJobs,
  reprocessSingleAutopilotJob,
  resetSingleAutopilotJob,
  skipStagedApplication,
  TailorDiffResponse,
} from "@/lib/application-assistant-api";
import { PreflightReviewModal } from "@/components/application-assistant/preflight-review-modal";
import { ApplicationQueueCard, type QueueApplication } from "@/components/application-assistant/application-queue-card";
import { resolveApplicationReadiness } from "@/components/application-assistant/application-readiness";

export function ReviewCenter() {
  const [stagedList, setStagedList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editingAnswers, setEditingAnswers] = useState<Record<string, string>>({});
  const [diffModalData, setDiffModalData] = useState<TailorDiffResponse | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  const fetchStaged = async () => {
    try {
      const res = await getStagedApplications();
      setStagedList(res.staged || []);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not fetch review applications");
    }
  };

  useEffect(() => {
    fetchStaged();
  }, []);

  const handleApprove = async (jobId: string, questionText: string) => {
    setLoading(true);
    const answerToSubmit = editingAnswers[jobId] || "";
    try {
      await approveStagedAnswer(jobId, questionText, answerToSubmit);
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
      const res = await reprocessFailedAutopilotJobs();
      setMessage(res?.message || "Moved applications back to queue!");
      setTimeout(() => setMessage(null), 4000);
      await fetchStaged();
    } catch (err: any) {
      setError(err?.message || "Failed to requeue applications");
    } finally {
      setLoading(false);
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

            return (
              <ApplicationQueueCard
                key={job.id}
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
                errorSlot={
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300/15 bg-amber-300/[0.06] px-3.5 py-2.5 text-xs text-amber-100">
                    <span className="line-clamp-1 truncate max-w-[200px]" title={job.aiExplanation || explanationSummary}>
                      {explanationSummary}
                    </span>
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() => void handleQuickApply(job)}
                        disabled={loading}
                        className="rounded-lg bg-gradient-to-r from-amber-500/30 to-teal-500/30 text-amber-200 border border-amber-500/50 hover:bg-amber-500/40 px-3 py-1 font-bold transition flex items-center gap-1.5 shadow-sm disabled:opacity-50 cursor-pointer"
                        title="Open Chrome window with saved autofill state to review and submit"
                      >
                        <span>⚡ Quick Apply</span>
                      </button>
                      {(job.applicationUrl || job.listingUrl) && (
                        <a
                          href={job.applicationUrl || job.listingUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded-lg border border-white/10 bg-white/[0.05] px-2.5 py-1 font-medium text-slate-200 transition hover:bg-white/[0.10]"
                        >
                          View link
                        </a>
                      )}
                      <button
                        type="button"
                        onClick={() => void reprocessSingleAutopilotJob(job.id).then(fetchStaged)}
                        disabled={loading}
                        className="rounded-lg bg-cyan-400/20 text-cyan-200 border border-cyan-400/30 px-2.5 py-1 font-medium transition hover:bg-cyan-400/30 disabled:opacity-50"
                        title="Move this job back to the Autopilot queue"
                      >
                        Queue
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleApprove(job.id, primaryQ.question || "")}
                        disabled={loading}
                        className="rounded-lg bg-emerald-500/25 text-emerald-200 border border-emerald-500/40 px-2.5 py-1 font-semibold transition hover:bg-emerald-500/40 hover:text-white flex items-center gap-1 disabled:opacity-50"
                        title="Approve and submit application"
                      >
                        Approve
                      </button>
                    </div>
                  </div>
                }
              />
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
