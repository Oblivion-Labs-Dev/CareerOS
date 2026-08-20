"use client";

import React, { useEffect, useState } from "react";
import {
  approveStagedAnswer,
  getStagedApplications,
  skipStagedApplication,
} from "@/lib/application-assistant-api";

export function ReviewCenter() {
  const [stagedList, setStagedList] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingAnswers, setEditingAnswers] = useState<Record<string, string>>({});

  const fetchStaged = async () => {
    try {
      const res = await getStagedApplications();
      setStagedList(res.staged || []);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not fetch staged applications");
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

  return (
    <div className="space-y-6 font-sans">
      {/* Header Banner */}
      <div className="p-6 rounded-2xl border border-amber-500/25 bg-gradient-to-br from-[#141009] via-[#1a140b] to-[#0c0a06] backdrop-blur-2xl shadow-xl flex flex-wrap justify-between items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <span>📋</span> Review Center (Needs Review)
          </h2>
          <p className="text-xs text-slate-300 mt-1">
            Applications staged due to ambiguous, sensitive, or low-confidence questions. Approve or edit answers to re-queue.
          </p>
        </div>
        <span className="px-3.5 py-1 text-xs font-bold rounded-full bg-amber-500/15 border border-amber-500/40 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.25)]">
          {stagedList.length} Staged
        </span>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
          {error}
        </div>
      )}

      {stagedList.length === 0 ? (
        <div className="p-12 text-center border border-dashed border-white/10 rounded-2xl text-slate-500 text-xs bg-[#0d121c]/40">
          No applications staged for review! All applications are processed automatically.
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
                    <span className="px-2.5 py-1 text-xs rounded-full bg-[#2ee8c9]/15 text-[#2ee8c9] border border-[#2ee8c9]/30 font-semibold">
                      Match {job.matchScore}%
                    </span>
                  </div>
                </div>

                {job.aiExplanation && (
                  <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/25 text-xs text-amber-200">
                    <strong className="text-amber-300">Reason Staged:</strong> {job.aiExplanation}
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
    </div>
  );
}
