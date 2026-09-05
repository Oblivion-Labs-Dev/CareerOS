"use client";

import React, { useEffect, useState } from "react";
import {
  deleteAutopilotJob,
  getAutopilotJobs,
  reprocessSingleAutopilotJob,
  reprocessSkippedAutopilotJobs,
} from "@/lib/application-assistant-api";

const EXPIRED_REASON_PATTERNS = [
  "no longer open",
  "no longer active",
  "no longer accepting",
  "no longer available",
  "position has been filled",
  "posting has expired",
  "job is closed",
  "page not found",
];

function looksExpired(reason: string): boolean {
  const lower = reason.toLowerCase();
  return EXPIRED_REASON_PATTERNS.some((p) => lower.includes(p));
}
import { IconCheckCircle, IconClock } from "@/components/application-assistant/autopilot/icons";
import { ApplicationQueueCard, type QueueApplication } from "@/components/application-assistant/application-queue-card";
import { resolveApplicationReadiness } from "@/components/application-assistant/application-readiness";

export function SkippedJobsCenter() {
  const [skippedList, setSkippedList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchSkipped = async () => {
    setLoading(true);
    try {
      const res = await getAutopilotJobs("SKIPPED");
      setSkippedList(res.jobs || []);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not fetch skipped applications");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkipped();
  }, []);

  const handleRequeue = async (id: string, title: string) => {
    setBusy(true);
    setError(null);
    try {
      await reprocessSingleAutopilotJob(id);
      setSuccessMsg(`Requeued "${title}" for another autopilot attempt.`);
      await fetchSkipped();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Failed to requeue application");
    } finally {
      setBusy(false);
    }
  };

  const handleRequeueAll = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await reprocessSkippedAutopilotJobs();
      setSuccessMsg(res.message || `Moved ${res.reprocessedCount ?? "all"} skipped application(s) back to the queue.`);
      await fetchSkipped();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to move skipped applications to the queue");
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async (id: string, title: string) => {
    if (!confirm(`Remove "${title}" from processing?`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteAutopilotJob(id);
      setSuccessMsg(`Removed "${title}" from processing.`);
      await fetchSkipped();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Failed to remove application");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 font-sans">
      <div className="p-6 rounded-2xl border border-amber-500/25 bg-gradient-to-br from-[#1a1408] via-[#1e1a0d] to-[#100c04] backdrop-blur-2xl shadow-xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <IconClock className="w-5 h-5 text-amber-300" />
            <span>Skipped Applications</span>
          </h2>
          <p className="text-xs text-slate-300 mt-1">
            Jobs Autopilot deliberately did not apply to — usually a hard filter (sponsorship, role, or location mismatch). Requeue if the filter was wrong.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="px-3.5 py-1 text-xs font-bold rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-300">
            {skippedList.length} Skipped
          </span>
          {skippedList.length > 0 && (
            <button
              onClick={handleRequeueAll}
              disabled={busy || loading}
              className="px-3.5 py-1 text-xs font-bold text-amber-200 hover:text-white bg-amber-500/15 hover:bg-amber-500/25 rounded-xl border border-amber-400/30 transition-all cursor-pointer disabled:opacity-50"
              title="Move every skipped application back to the queue"
            >
              {busy ? "Moving..." : "↻ Move All to Queue"}
            </button>
          )}
          <button
            onClick={fetchSkipped}
            disabled={loading}
            className="px-3 py-1 text-xs font-semibold text-slate-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 transition-all cursor-pointer"
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2">
          <IconCheckCircle className="w-4 h-4" />
          <span>{successMsg}</span>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">{error}</div>
      )}

      {skippedList.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No skipped applications currently recorded.
        </div>
      ) : (
        <div className="aa-queue-grid">
          {skippedList.map((job) => {
            const reason = job.skipReason || job.aiExplanation || "Skipped by a hard filter (sponsorship, role, or location mismatch).";
            const expired = looksExpired(reason);
            const app: QueueApplication = {
              id: job.id,
              jobId: job.jobId || job.id,
              companyName: job.company || "Unknown company",
              roleTitle: job.title || "Unknown role",
              provider: job.provider || job.sourceProvider || "Autopilot",
              status: "blocked",
              progress: 0,
              verifiedCount: 0,
              reviewCount: 0,
              missingCount: 0,
              conflictingCount: 0,
              matchScore: job.matchScore,
              updatedAt: job.updatedAt || new Date().toISOString(),
              errors: [{ error: reason }],
              fields: [],
            };

            return (
              <ApplicationQueueCard
                key={job.id}
                app={app}
                statusAccent="amber"
                isOpening={false}
                isBrowserOpen={false}
                isAnalyzing={false}
                isWizardLoading={false}
                gateLoading={false}
                profileBlocked={false}
                readiness={resolveApplicationReadiness(app)}
                needsAiAnalysis={false}
                pendingCount={0}
                isPreparing={busy}
                isActivePrep={false}
                openingElapsedSec={0}
                analyzeElapsedSec={0}
                closingBrowser={false}
                onFocusBrowser={() => undefined}
                onResume={expired ? () => undefined : () => void handleRequeue(job.id, job.title || "Job")}
                onAnswerQuestions={() => undefined}
                onOpenInBrowser={() => undefined}
                onToggleSubmitted={() => undefined}
                onArchive={() => void handleRemove(job.id, job.title || "Job")}
                intelligenceSlot={<p className="aac-alert aac-alert--info">{reason}</p>}
                primaryActionOverride={{
                  label: expired ? "No longer available" : "Requeue",
                  onClick: () => void handleRequeue(job.id, job.title || "Job"),
                  disabled: busy || expired,
                }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
