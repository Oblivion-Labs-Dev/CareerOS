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
  IconClock,
  IconExternalLink,
  IconRefresh,
  IconTrash,
} from "@/components/application-assistant/autopilot/icons";

export function FailedJobsCenter({ onReprocessSuccess }: { onReprocessSuccess?: () => void }) {
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
      setSuccessMsg(res.message || "Re-queued all failed applications with self-healing loop!");
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
              Copy AI troubleshooting prompt
            </button>
          )}
          {failedList.length > 0 && (
            <button
              onClick={handleReprocessAll}
              disabled={reprocessing || loading}
              className="rounded-xl bg-cyan-300 px-4 py-2.5 text-xs font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
            >
              {reprocessing ? "Preparing retries…" : "Retry eligible applications"}
            </button>
          )}

          <button
            onClick={fetchFailed}
            disabled={loading}
            className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5 text-xs font-medium text-slate-300 transition hover:bg-white/[0.08]"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center justify-between">
          <span>✓ {successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-400 font-bold hover:text-emerald-200 cursor-pointer">✕</button>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {loading && failedList.length === 0 ? (
        <div className="p-12 text-center border border-white/10 rounded-2xl text-slate-400 text-xs bg-[#0d121c]/40 flex flex-col items-center justify-center gap-2">
          <div className="w-6 h-6 rounded-full border-2 border-[#2ee8c9] border-t-transparent animate-spin" />
          <span>Loading failed applications...</span>
        </div>
      ) : failedList.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No failed applications! Everything is either successfully submitted, queued, or running.
        </div>
      ) : (
        <div className="space-y-4">
          {failedList.map((job) => {
            const appUrl = job.applicationUrl || job.listingUrl || "";

            return (
              <div
                key={job.id}
                className="p-5 rounded-2xl border border-white/[0.08] bg-[#0b121f] space-y-4 transition hover:border-white/[0.14]"
              >
                <div className="flex flex-wrap justify-between items-start gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-extrabold text-white">{job.title}</h3>
                      <span className="px-2.5 py-0.5 rounded-full text-[10px] font-medium bg-rose-300/10 text-rose-200 uppercase tracking-wider">
                        Needs review
                      </span>
                    </div>
                    <p className="text-xs font-semibold text-slate-400">{job.company}</p>
                  </div>

                  <div className="flex items-center gap-2">
                    {job.matchScore && (
                      <span className="px-2.5 py-1 text-xs rounded-full bg-[#2ee8c9]/15 text-[#2ee8c9] border border-[#2ee8c9]/30 font-semibold">
                        Match {job.matchScore}%
                      </span>
                    )}

                    {appUrl && (
                      <a
                        href={appUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                      className="px-3 py-2 text-xs rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 border border-white/10 transition flex items-center gap-1.5"
                      >
                        <span>Open Job Listing</span>
                        <IconExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}

                    <button
                      onClick={() => handleResetSingle(job.id, job.title)}
                      disabled={reprocessing}
                      className="px-3 py-2 text-xs rounded-xl bg-white/[0.04] hover:bg-white/[0.08] text-slate-300 border border-white/10 transition font-medium"
                      title="Reset this job back to unapplied state"
                    >
                      Reset
                    </button>

                    <button
                      onClick={() => handleDeleteSingle(job.id, job.title)}
                      disabled={reprocessing}
                      className="px-3 py-2 text-xs rounded-xl bg-white/[0.04] border border-white/10 text-rose-200 hover:bg-rose-300/[0.08] transition font-medium flex items-center gap-1.5 disabled:opacity-40"
                      title="Remove this application from Autopilot processing"
                    >
                      <IconTrash className="w-3.5 h-3.5" />
                      <span>Remove</span>
                    </button>

                    <button
                      onClick={() => handleReprocessSingle(job.id, job.title)}
                      disabled={reprocessing}
                      className="px-3.5 py-2 text-xs rounded-xl bg-cyan-300 text-slate-950 font-semibold hover:bg-cyan-200 transition flex items-center gap-1.5"
                    >
                      <span>Retry with checks</span>
                    </button>
                  </div>
                </div>

                {job.lastError && (
                  <div className="p-3.5 rounded-xl bg-rose-300/[0.06] border border-rose-300/[0.12] text-xs text-rose-100 space-y-2">
                    <div className="font-medium text-rose-200 flex items-center gap-1.5">
                        <IconAlertCircle className="w-4 h-4 text-rose-400" />
                        <span>What needs attention</span>
                    </div>
                    <p className="text-[11px] leading-relaxed text-rose-100/80 pl-5">
                      {job.lastError}
                    </p>
                    <div className="pl-5 pt-1">
                      <button
                        type="button"
                        onClick={() => handleCopyError(job)}
                        className="rounded-lg border border-rose-300/20 bg-rose-300/[0.06] px-2.5 py-1.5 text-[11px] font-medium text-rose-100 transition hover:bg-rose-300/[0.12]"
                      >
                        Copy error
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
