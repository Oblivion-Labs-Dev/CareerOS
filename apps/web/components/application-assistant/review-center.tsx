"use client";

import React, { useEffect, useState } from "react";
import {
  approveStagedAnswer,
  getJobTailorDiff,
  getStagedApplications,
  reprocessSingleAutopilotJob,
  resetSingleAutopilotJob,
  resetSubmittedAutopilotJobs,
  skipStagedApplication,
  TailorDiffResponse,
} from "@/lib/application-assistant-api";
import { PreflightReviewModal } from "@/components/application-assistant/preflight-review-modal";

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

  const handleResetAllStaged = async () => {
    if (!confirm("Are you sure you want to reset all staged applications back to unapplied?")) {
      return;
    }
    setLoading(true);
    try {
      const res = await resetSubmittedAutopilotJobs("STAGED");
      setMessage(res?.message || "All staged applications reset to unapplied");
      setTimeout(() => setMessage(null), 3500);
      await fetchStaged();
    } catch (err: any) {
      setError(err?.message || "Failed to reset staged applications");
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
        <div className="flex items-center gap-3">
          <span className="px-3.5 py-1 text-xs font-bold rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.25)]">
            {stagedList.length} In Review
          </span>
          {stagedList.length > 0 && (
            <button
              onClick={handleResetAllStaged}
              disabled={loading}
              className="px-3.5 py-1 text-xs font-bold text-amber-300 hover:text-amber-200 bg-amber-500/10 hover:bg-amber-500/20 rounded-xl border border-amber-500/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
              title="Reset all staged applications to unapplied"
            >
              <span>↺</span> Reset All Staged
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
        <div className="space-y-4">
          {stagedList.map((job) => {
            const unresolved = job.unresolvedQuestions || [];
            const primaryQ = unresolved[0] || {};
            return (
              <div
                key={job.id}
                className="p-5 rounded-2xl border border-white/10 bg-[#0d121c]/80 backdrop-blur-xl space-y-4 hover:border-amber-500/30 transition-all shadow-lg"
              >
                <div className="flex flex-wrap justify-between items-start gap-2">
                  <div>
                    <h3 className="text-base font-extrabold text-white">{job.title}</h3>
                    <p className="text-xs text-slate-400 mt-0.5">{job.company}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleOpenDiff(job)}
                      disabled={diffLoading}
                      className="px-3 py-1 text-xs rounded-xl bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-300 border border-cyan-500/40 transition-all font-bold flex items-center gap-1.5 cursor-pointer shadow-[0_0_12px_rgba(6,182,212,0.25)]"
                    >
                      <span>🔍</span>
                      <span>Pre-Flight Diff</span>
                    </button>
                    <span className="px-2.5 py-1 text-xs rounded-full bg-[#2ee8c9]/15 text-[#2ee8c9] border border-[#2ee8c9]/30 font-semibold">
                      Match {job.matchScore}%
                    </span>
                    {(job.applicationUrl || job.listingUrl) && (
                      <a
                        href={job.applicationUrl || job.listingUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2.5 py-1 text-xs rounded-xl bg-white/5 hover:bg-[#38bdf8]/15 text-[#38bdf8] border border-white/10 hover:border-[#38bdf8]/40 transition-all font-semibold flex items-center gap-1"
                      >
                        <span>Listing ↗</span>
                      </a>
                    )}
                  </div>
                </div>

                {job.aiExplanation && (
                  <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/25 text-xs text-amber-200">
                    <strong className="text-amber-300">Reason for Review:</strong> {job.aiExplanation}
                  </div>
                )}

                {primaryQ.question && (
                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-slate-300">
                      Unresolved Question: &ldquo;{primaryQ.question}&rdquo;
                    </label>
                    <input
                      type="text"
                      placeholder="Type your approved answer here..."
                      value={editingAnswers[job.id] ?? (primaryQ.proposedAnswer || "")}
                      onChange={(e) =>
                        setEditingAnswers({ ...editingAnswers, [job.id]: e.target.value })
                      }
                      className="w-full px-3.5 py-2 text-xs rounded-xl bg-[#06090e] border border-white/15 text-slate-100 focus:outline-none focus:border-[#2ee8c9] transition-all"
                    />
                  </div>
                )}

                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    onClick={() => handleResetSingle(job.id)}
                    disabled={loading}
                    className="px-3.5 py-2 rounded-xl text-xs font-semibold text-amber-300 hover:text-amber-200 border border-amber-500/30 hover:border-amber-500/50 bg-amber-500/10 hover:bg-amber-500/15 transition-all cursor-pointer flex items-center gap-1"
                    title="Reset this job back to unapplied"
                  >
                    <span>↺</span> Reset
                  </button>
                  <button
                    onClick={async () => {
                      setLoading(true);
                      try {
                        await reprocessSingleAutopilotJob(job.id);
                        setMessage(`Queued "${job.title}" for self-healing reprocessing`);
                        setTimeout(() => setMessage(null), 3500);
                        await fetchStaged();
                      } catch (err: any) {
                        setError(err?.message || "Failed to reprocess job");
                      } finally {
                        setLoading(false);
                      }
                    }}
                    disabled={loading}
                    className="px-4 py-2 rounded-xl text-xs font-bold text-amber-300 bg-amber-500/15 border border-amber-500/40 hover:bg-amber-500/25 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
                  >
                    <span>⚡ Reprocess with Self-Healing</span>
                  </button>
                  <button
                    onClick={() => handleSkip(job.id)}
                    disabled={loading}
                    className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-slate-200 border border-white/10 hover:border-white/20 transition-all cursor-pointer"
                  >
                    Skip Job
                  </button>
                  <button
                    onClick={() => handleApprove(job.id, primaryQ.question || "")}
                    disabled={loading}
                    className="px-5 py-2 rounded-xl text-xs font-extrabold bg-gradient-to-r from-emerald-400 via-teal-400 to-cyan-500 text-slate-950 shadow-[0_0_15px_rgba(46,232,201,0.3)] hover:shadow-[0_0_20px_rgba(46,232,201,0.5)] hover:scale-[1.02] active:scale-[0.98] transition-all cursor-pointer"
                  >
                    Approve & Re-queue
                  </button>
                </div>
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
