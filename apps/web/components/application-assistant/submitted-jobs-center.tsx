"use client";

import React, { useEffect, useState } from "react";
import {
  getAutopilotJobs,
  resetSingleAutopilotJob,
  resetSubmittedAutopilotJobs,
} from "@/lib/application-assistant-api";
import { IconCheckCircle, IconExternalLink, IconSend } from "@/components/application-assistant/autopilot/icons";

export function SubmittedJobsCenter() {
  const [submittedList, setSubmittedList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const fetchSubmitted = async () => {
    setLoading(true);
    try {
      const res = await getAutopilotJobs("SUBMITTED");
      setSubmittedList(res.jobs || []);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not fetch submitted jobs");
    } finally {
      setLoading(false);
    }
  };

  const handleResetAll = async () => {
    if (!confirm("Are you sure you want to reset all submitted jobs back to UNAPPLIED so they can be re-applied?")) {
      return;
    }
    setResetting(true);
    setError(null);
    try {
      const res = await resetSubmittedAutopilotJobs("SUBMITTED");
      setSuccessMsg(res.message || "Submitted jobs reset to unapplied");
      await fetchSubmitted();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to reset submitted jobs");
    } finally {
      setResetting(false);
    }
  };

  const handleResetSingle = async (id: string, title: string) => {
    setResetting(true);
    setError(null);
    try {
      await resetSingleAutopilotJob(id);
      setSuccessMsg(`Reset "${title}" back to unapplied.`);
      await fetchSubmitted();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Failed to reset job");
    } finally {
      setResetting(false);
    }
  };

  useEffect(() => {
    fetchSubmitted();
  }, []);

  return (
    <div className="space-y-6 font-sans">
      {/* Header Banner */}
      <div className="p-6 rounded-2xl border border-emerald-500/25 bg-gradient-to-br from-[#0a161f] via-[#0d1e2a] to-[#071017] backdrop-blur-2xl shadow-xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <IconSend className="w-5 h-5 text-[#2ee8c9]" />
            <span>Submitted Applications</span>
          </h2>
          <p className="text-xs text-slate-300 mt-1">
            All applications processed by Autopilot. You can review them or reset them back to unapplied for re-execution.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="px-3.5 py-1 text-xs font-bold rounded-full bg-emerald-500/15 border border-emerald-500/40 text-[#2ee8c9] shadow-[0_0_12px_rgba(46,232,201,0.25)]">
            {submittedList.length} Submitted
          </span>
          {submittedList.length > 0 && (
            <button
              onClick={handleResetAll}
              disabled={resetting || loading}
              className="px-3.5 py-1 text-xs font-bold text-amber-300 hover:text-amber-200 bg-amber-500/10 hover:bg-amber-500/20 rounded-xl border border-amber-500/30 transition-all cursor-pointer flex items-center gap-1.5 shadow-sm"
              title="Reset all submitted applications back to Unapplied"
            >
              <span>↺</span>
              <span>{resetting ? "Resetting..." : "Reset All to Unapplied"}</span>
            </button>
          )}
          <button
            onClick={fetchSubmitted}
            disabled={loading}
            className="px-3 py-1 text-xs font-semibold text-slate-300 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 transition-all cursor-pointer"
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {successMsg && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs flex items-center justify-between">
          <span>✓ {successMsg}</span>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-400 font-bold hover:text-emerald-200">✕</button>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {submittedList.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No submitted applications currently recorded. All jobs are ready in unapplied state.
        </div>
      ) : (
        <div className="space-y-4">
          {submittedList.map((job) => {
            const submittedAt = job.submittedAt
              ? new Date(job.submittedAt).toLocaleString()
              : job.updatedAt
              ? new Date(job.updatedAt).toLocaleString()
              : "N/A";
            const appUrl = job.applicationUrl || job.listingUrl || "";
            const evidence = job.submissionEvidence || {};

            return (
              <div
                key={job.id}
                className="p-5 rounded-2xl border border-white/10 bg-[#0d1420]/80 backdrop-blur-xl space-y-4 hover:border-emerald-500/40 transition-all shadow-lg"
              >
                <div className="flex flex-wrap justify-between items-start gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-extrabold text-white">{job.title}</h3>
                      <span className="px-2.5 py-0.5 rounded-full text-[10px] font-black bg-emerald-500/20 text-[#2ee8c9] border border-emerald-500/40 uppercase tracking-wider">
                        Submitted ✓
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
                        className="px-3 py-1 text-xs rounded-xl bg-white/5 hover:bg-[#38bdf8]/15 text-[#38bdf8] border border-white/10 hover:border-[#38bdf8]/40 transition-all font-semibold flex items-center gap-1.5"
                      >
                        <span>View Job Listing</span>
                        <IconExternalLink className="w-3.5 h-3.5" />
                      </a>
                    )}
                    <button
                      onClick={() => handleResetSingle(job.id, job.title)}
                      disabled={resetting}
                      className="px-2.5 py-1 text-xs rounded-xl bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/25 transition-all font-medium flex items-center gap-1 cursor-pointer"
                      title="Reset this job back to unapplied"
                    >
                      <span>↺ Reset to Unapplied</span>
                    </button>
                  </div>
                </div>

                {/* Details & Submission Evidence */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3.5 rounded-xl bg-[#060a10] border border-white/5 text-xs">
                  <div>
                    <span className="text-slate-500 font-mono block text-[11px]">SUBMITTED AT</span>
                    <span className="text-slate-200 font-medium">{submittedAt}</span>
                  </div>
                  <div>
                    <span className="text-slate-500 font-mono block text-[11px]">EVIDENCE / ATS STATUS</span>
                    <span className="text-emerald-400 font-medium">
                      {evidence.confirmationText || "Application confirmed by ATS"}
                    </span>
                  </div>
                  {job.answers && Object.keys(job.answers).length > 0 && (
                    <div className="sm:col-span-2 pt-1 border-t border-white/5">
                      <span className="text-slate-500 font-mono block text-[11px] mb-1">FIELDS FILLED</span>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(job.answers).map(([key, val]) => (
                          <span
                            key={key}
                            className="px-2 py-0.5 rounded-md bg-white/5 text-[11px] text-slate-300 font-mono"
                          >
                            {key}: <strong className="text-slate-100">{String(val)}</strong>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

