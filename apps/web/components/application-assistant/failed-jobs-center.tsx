"use client";

import React, { useEffect, useState } from "react";
import {
  deleteAutopilotJob,
  getAutopilotJobs,
  reprocessFailedAutopilotJobs,
  reprocessSingleAutopilotJob,
  resetSingleAutopilotJob,
} from "@/lib/application-assistant-api";
import {
  IconAlertCircle,
  IconCheck,
  IconClock,
  IconExternalLink,
  IconRefresh,
  IconTrash,
} from "@/components/application-assistant/autopilot/icons";
import { ApplicationQueueCard, type QueueApplication } from "@/components/application-assistant/application-queue-card";
import { resolveApplicationReadiness } from "@/components/application-assistant/application-readiness";
import { openApplicationReview } from "@/lib/application-assistant-api";

export function FailedJobsCenter({ onReprocessSuccess, onOpenPrep }: { onReprocessSuccess?: () => void; onOpenPrep?: () => void }) {
  const [failedList, setFailedList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchFailed = async () => {
    setLoading(true);
    try {
      const res = await getAutopilotJobs("FAILED");
      setFailedList(res.jobs || []);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not fetch failed applications");
    } finally {
      setLoading(false);
    }
  };

  const handleReprocessAll = async () => {
    setReprocessing(true);
    setError(null);
    try {
      const res = await reprocessFailedAutopilotJobs();
      setSuccessMsg(res.message || "Failed applications are queued and waiting for you to start a run.");
      await fetchFailed();
      if (onReprocessSuccess) onReprocessSuccess();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to reprocess jobs");
    } finally {
      setReprocessing(false);
    }
  };

  const handleReprocessSingle = async (id: string, title: string) => {
    setReprocessing(true);
    setError(null);
    try {
      const res = await reprocessSingleAutopilotJob(id);
      setSuccessMsg(`Queued "${title}" for self-healing reprocessing.`);
      await fetchFailed();
      if (onReprocessSuccess) onReprocessSuccess();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Failed to reprocess application");
    } finally {
      setReprocessing(false);
    }
  };

  const handleResetSingle = async (id: string, title: string) => {
    setReprocessing(true);
    setError(null);
    try {
      await resetSingleAutopilotJob(id);
      setSuccessMsg(`Reset "${title}" to unapplied.`);
      await fetchFailed();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Failed to reset application");
    } finally {
      setReprocessing(false);
    }
  };

  const handleDeleteSingle = async (id: string, title: string) => {
    if (!confirm(`Remove "${title}" from processing?`)) return;
    setReprocessing(true);
    setError(null);
    try {
      await deleteAutopilotJob(id);
      setSuccessMsg(`Removed "${title}" from processing.`);
      await fetchFailed();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Failed to remove application");
    } finally {
      setReprocessing(false);
    }
  };

  const handleCopyError = async (job: any) => {
    const errorDetails = `${job.company || "Company"} · ${job.title || "Application"}\n\n${job.lastError || "No error details recorded."}`;
    try {
      await navigator.clipboard.writeText(errorDetails);
      setSuccessMsg("Error details copied to your clipboard.");
      setTimeout(() => setSuccessMsg(null), 2500);
    } catch {
      setError("Could not copy the error details. Please select the text and copy it manually.");
    }
  };

  const handleCopyAllErrors = async () => {
    const prompt = [
      "Investigate and propose a safe fix for these CareerOS job-application failures.",
      "Do not submit any application. Diagnose the form-filling or confirmation issue from the supplied evidence.",
      "",
      ...failedList.map((job, index) => {
        const evidence = job.submissionEvidence || {};
        return [
          `${index + 1}. ${job.company || "Unknown company"} — ${job.title || "Unknown role"}`,
          `Job URL: ${job.applicationUrl || job.listingUrl || "Not recorded"}`,
          `Job ID: ${job.id || job.jobId || "Not recorded"}`,
          `Error type: ${job.lastErrorType || "Not recorded"}`,
          `Error: ${job.lastError || job.failureReason || job.aiExplanation || "Not recorded"}`,
          `Confirmation URL: ${evidence.confirmationUrl || "Not recorded"}`,
          `Screenshot evidence: ${evidence.screenshotPath || evidence.preScreenshotPath || "Not recorded"}`,
        ].join("\n");
      }),
    ].join("\n\n");

    try {
      await navigator.clipboard.writeText(prompt);
      setSuccessMsg(`Copied ${failedList.length} failure${failedList.length === 1 ? "" : "s"} as an AI-ready prompt.`);
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch {
      setError("Could not copy the troubleshooting prompt. Please try again.");
    }
  };

  const handleQuickApply = async (job: any) => {
    setReprocessing(true);
    setError(null);
    const url = job.applicationUrl || job.listingUrl;
    
    // Immediately open in a new window/tab so user is never blocked or left with just a text message
    if (url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }

    try {
      const rawJobId = String(job.jobId || job.id || "");
      const cleanJobId = rawJobId.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
      const appId = `app_${cleanJobId}`.slice(0, 120);
      
      // Also request backend open-review to launch playwright/autofill in background if active
      const result = await openApplicationReview(appId, { force: true }).catch(() => null);
      if (result?.success) {
        setSuccessMsg(`Opened "${job.title}" in a browser window with autofilled profile data. Review and click Submit!`);
      } else if (url) {
        setSuccessMsg(`Opened "${job.title}" in a browser tab.`);
      } else {
        throw new Error("No application URL available for this job.");
      }
      setTimeout(() => setSuccessMsg(null), 5000);
    } catch (err: any) {
      if (url) {
        setSuccessMsg(`Opened "${job.title}" in a browser tab.`);
        setTimeout(() => setSuccessMsg(null), 4000);
      } else {
        setError(err?.message || "Could not open application URL");
      }
    } finally {
      setReprocessing(false);
    }
  };

  useEffect(() => {
    fetchFailed();
  }, []);

  return (
    <div className="space-y-5">
      <div className="relative overflow-hidden rounded-[28px] border border-white/[0.08] bg-[#0a101b] p-6 sm:p-8 shadow-[0_24px_80px_rgba(0,0,0,0.28)]">
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-rose-300/80 to-transparent" />
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-white flex items-center gap-2.5">
            <IconAlertCircle className="w-5 h-5 text-rose-300" />
            <span>Needs attention</span>
          </h2>
          <p className="max-w-2xl text-sm text-slate-400 mt-2">
            Review each blocker before retrying. CareerOS will only continue when the form can be verified safely.
          </p>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-rose-300/10 px-3 py-1.5 text-xs font-medium text-rose-200">
            {failedList.length} require review
          </span>
          {failedList.length > 0 && (
            <button
              type="button"
              onClick={handleCopyAllErrors}
              className="rounded-xl border border-violet-300/25 bg-violet-300/[0.08] px-3.5 py-2.5 text-xs font-medium text-violet-100 transition hover:bg-violet-300/[0.14]"
            >
              Copy all errors for LLM
            </button>
          )}
          {failedList.length > 0 && (
            <button
              type="button"
              onClick={handleReprocessAll}
              disabled={reprocessing || loading}
              className="rounded-xl border border-rose-300/25 bg-rose-300/[0.08] px-3.5 py-2.5 text-xs font-medium text-rose-100 transition hover:bg-rose-300/[0.14] disabled:opacity-50"
            >
              {reprocessing ? "Retrying all…" : "Retry all failed"}
            </button>
          )}
          <button
            type="button"
            onClick={fetchFailed}
            disabled={loading}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-xs font-medium text-slate-300 transition hover:bg-white/[0.08] disabled:opacity-50"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-xs text-rose-200">
          <IconAlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{error}</span>
        </div>
      )}

      {successMsg && (
        <div className="flex items-center gap-2.5 rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-xs text-emerald-200">
          <IconCheck className="w-4 h-4 shrink-0 text-emerald-400" />
          <span>{successMsg}</span>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-slate-400 text-xs gap-2">
          <IconRefresh className="w-4 h-4 animate-spin text-rose-300" />
          <span>Loading failed applications...</span>
        </div>
      ) : failedList.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No failed applications! Everything is either successfully submitted, queued, or running.
        </div>
      ) : (
        <div className="aa-queue-grid">
          {failedList.map((job) => {
            const queueApp: QueueApplication = {
              id: job.id,
              jobId: job.jobId || job.id,
              companyName: job.company || "Unknown company",
              roleTitle: job.title || "Unknown role",
              provider: job.provider || job.sourceProvider || "unknown",
              status: "failed",
              progress: 0.7,
              verifiedCount: Object.keys(job.answers || {}).length,
              reviewCount: 0,
              missingCount: 0,
              conflictingCount: 0,
              matchScore: job.matchScore,
              updatedAt: job.updatedAt || new Date().toISOString(),
              hasSavedAutofillState: Object.keys(job.answers || {}).length > 0,
              quickApplyAvailable: true,
              autofillStepCount: Object.keys(job.answers || {}).length,
              quickApplyStepCount: Object.keys(job.answers || {}).length,
              quickApplyLabel: "⚡ Quick apply now",
              errors: [],
              lastPrepFailed: false,
              fields: Object.keys(job.answers || {}).map((label) => ({ label, classification: "verified" })),
            };
            const readiness = resolveApplicationReadiness(queueApp);

            return (
              <ApplicationQueueCard
                key={job.id}
                app={queueApp}
                statusAccent="rose"
                isOpening={false}
                isBrowserOpen={false}
                isAnalyzing={false}
                isWizardLoading={false}
                gateLoading={false}
                profileBlocked={false}
                readiness={readiness}
                needsAiAnalysis={false}
                pendingCount={0}
                isPreparing={reprocessing}
                isActivePrep={false}
                openingElapsedSec={0}
                analyzeElapsedSec={0}
                closingBrowser={false}
                onFocusBrowser={() => undefined}
                onResume={() => void handleQuickApply(job)}
                onAnswerQuestions={() => void handleQuickApply(job)}
                onOpenInBrowser={() => void handleQuickApply(job)}
                onToggleSubmitted={() => undefined}
                onArchive={() => void handleDeleteSingle(job.id, job.title || "Job")}
                primaryActionOverride={{
                  label: "⚡ Quick Apply",
                  onClick: () => void handleQuickApply(job),
                  disabled: reprocessing,
                }}
                intelligenceSlot={
                  <div className="w-full flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleQuickApply(job);
                      }}
                      disabled={reprocessing}
                      className="w-full rounded-xl bg-gradient-to-r from-emerald-500/25 via-teal-500/20 to-emerald-500/25 hover:from-emerald-500/35 hover:to-teal-500/35 text-emerald-200 border border-emerald-500/40 hover:border-emerald-400/60 py-2 px-3 font-semibold text-xs transition flex items-center justify-center gap-1.5 shadow-sm shadow-emerald-950/40 cursor-pointer disabled:opacity-50"
                      title="Directly open application window to review and submit"
                    >
                      <span className="text-emerald-300">⚡</span>
                      <span>Quick Apply in New Window</span>
                      <span className="text-emerald-400 font-normal">→</span>
                    </button>
                  </div>
                }
                errorSlot={
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-300/15 bg-rose-300/[0.06] px-3.5 py-2.5 text-xs text-rose-100">
                    <span className="line-clamp-2">{job.lastError || job.failureReason || "Application link expired or needs review"}</span>
                    <div className="flex shrink-0 items-center gap-2">
                      <button type="button" onClick={() => handleCopyError(job)} className="text-rose-200 underline underline-offset-2 px-1 text-xs">
                        Copy error
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleQuickApply(job)}
                        disabled={reprocessing}
                        className="rounded-lg bg-gradient-to-r from-emerald-500/30 to-teal-500/30 text-emerald-200 border border-emerald-500/50 hover:bg-emerald-500/40 px-3 py-1 font-bold transition flex items-center gap-1.5 shadow-sm disabled:opacity-50 cursor-pointer"
                        title="Open window with saved autofill state to review and submit"
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
                        onClick={() => void handleReprocessSingle(job.id, job.title || "Job")}
                        disabled={reprocessing}
                        className="rounded-lg bg-cyan-400/20 text-cyan-200 border border-cyan-400/30 px-2.5 py-1 font-medium transition hover:bg-cyan-400/30 disabled:opacity-50"
                        title="Retry processing this application"
                      >
                        Retry
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleDeleteSingle(job.id, job.title || "Job")}
                        disabled={reprocessing}
                        className="rounded-lg bg-rose-500/25 text-rose-200 border border-rose-500/40 px-2.5 py-1 font-semibold transition hover:bg-rose-500/40 hover:text-white flex items-center gap-1 disabled:opacity-50"
                        title="Permanently remove expired or dead link from all queues"
                      >
                        <IconTrash className="w-3.5 h-3.5" />
                        <span>Expire / Remove</span>
                      </button>
                    </div>
                  </div>
                }
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
