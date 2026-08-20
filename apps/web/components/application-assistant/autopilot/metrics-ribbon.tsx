"use client";

import React, { useState } from "react";
import {
  IconAlertCircle,
  IconCheckCircle,
  IconClock,
  IconExternalLink,
  IconInbox,
  IconSend,
  IconX,
} from "./icons";
import { getAutopilotJobs } from "@/lib/application-assistant-api";

interface MetricsRibbonProps {
  submitted: number;
  staged: number;
  skipped: number;
  failed: number;
  queueRemaining: number;
  processedCount: number;
  onSelectCategory?: (category: "SUBMITTED" | "STAGED" | "SKIPPED" | "FAILED" | "QUEUED") => void;
}

export function MetricsRibbon({
  submitted,
  staged,
  skipped,
  failed,
  queueRemaining,
  processedCount,
  onSelectCategory,
}: MetricsRibbonProps) {
  const [activeModalCategory, setActiveModalCategory] = useState<string | null>(null);
  const [modalJobs, setModalJobs] = useState<any[]>([]);
  const [loadingModal, setLoadingModal] = useState(false);

  const baseCount = Math.max(1, processedCount);
  const successPct = Math.round((submitted / baseCount) * 100);
  const stagedPct = Math.round((staged / baseCount) * 100);
  const skipPct = Math.round((skipped / baseCount) * 100);
  const failPct = Math.round((failed / baseCount) * 100);

  const handleCardClick = async (category: "SUBMITTED" | "STAGED" | "SKIPPED" | "FAILED" | "QUEUED") => {
    if (onSelectCategory) {
      onSelectCategory(category);
    }
    setActiveModalCategory(category);
    setLoadingModal(true);
    try {
      const res = await getAutopilotJobs(category === "QUEUED" ? "QUEUED" : category);
      setModalJobs(res.jobs || []);
    } catch {
      setModalJobs([]);
    } finally {
      setLoadingModal(false);
    }
  };

  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5 sm:gap-4">
        {/* 1. Submitted Card */}
        <div
          onClick={() => handleCardClick("SUBMITTED")}
          className="group relative overflow-hidden p-4 rounded-2xl border border-emerald-500/20 bg-gradient-to-b from-[#0b161f] to-[#070e16] shadow-xl hover:border-emerald-500/50 hover:shadow-[0_0_20px_rgba(46,232,201,0.25)] transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-[#2ee8c9]">
              <IconSend className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-[#2ee8c9] transition-colors">
              Submitted <span className="text-[9px] opacity-70">↗</span>
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-[#2ee8c9] tracking-tight">{submitted}</span>
            <span className="text-[11px] font-medium text-emerald-400/80">{successPct}% rate</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 20 Q30 18 60 12 T120 4"
                fill="none"
                stroke="#2ee8c9"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 2. Review Card */}
        <div
          onClick={() => handleCardClick("STAGED")}
          className="group relative overflow-hidden p-4 rounded-2xl border border-amber-500/20 bg-gradient-to-b from-[#14120e] to-[#0d0c09] shadow-xl hover:border-amber-500/50 hover:shadow-[0_0_20px_rgba(245,158,11,0.25)] transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center text-amber-400">
              <IconClock className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-amber-400 transition-colors">
              In Review <span className="text-[9px] opacity-70">↗</span>
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-amber-400 tracking-tight">{staged}</span>
            <span className="text-[11px] font-medium text-amber-400/80">{stagedPct}% review</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 16 Q30 8 60 18 T120 10"
                fill="none"
                stroke="#f59e0b"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 3. Skipped Card */}
        <div
          onClick={() => handleCardClick("SKIPPED")}
          className="group relative overflow-hidden p-4 rounded-2xl border border-indigo-500/20 bg-gradient-to-b from-[#10111e] to-[#0a0a14] shadow-xl hover:border-indigo-500/50 hover:shadow-[0_0_20px_rgba(99,102,241,0.25)] transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
              <IconInbox className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-indigo-400 transition-colors">
              Skipped <span className="text-[9px] opacity-70">↗</span>
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-indigo-400 tracking-tight">{skipped}</span>
            <span className="text-[11px] font-medium text-indigo-400/80">{skipPct}% skipped</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 18 Q40 14 80 16 T120 8"
                fill="none"
                stroke="#818cf8"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 4. Failed Card */}
        <div
          onClick={() => handleCardClick("FAILED")}
          className="group relative overflow-hidden p-4 rounded-2xl border border-rose-500/20 bg-gradient-to-b from-[#160e10] to-[#0e080a] shadow-xl hover:border-rose-500/50 hover:shadow-[0_0_20px_rgba(244,63,94,0.25)] transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-rose-400">
              <IconAlertCircle className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-rose-400 transition-colors">
              Failed <span className="text-[9px] opacity-70">↗</span>
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-rose-400 tracking-tight">{failed}</span>
            <span className="text-[11px] font-medium text-rose-400/80">{failPct}% error</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 20 Q40 20 80 16 T120 14"
                fill="none"
                stroke="#f43f5e"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>

        {/* 5. Queue Remaining Card */}
        <div
          onClick={() => handleCardClick("QUEUED")}
          className="group relative overflow-hidden p-4 rounded-2xl border border-cyan-500/20 bg-gradient-to-b from-[#0b1620] to-[#070e16] shadow-xl col-span-2 sm:col-span-1 hover:border-cyan-500/50 hover:shadow-[0_0_20px_rgba(56,189,248,0.25)] transition-all duration-300 cursor-pointer transform hover:-translate-y-0.5 active:scale-[0.98]"
        >
          <div className="flex items-center justify-between">
            <div className="w-8 h-8 rounded-xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center text-[#38bdf8]">
              <IconCheckCircle className="w-4 h-4" />
            </div>
            <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1 group-hover:text-[#38bdf8] transition-colors">
              Queue <span className="text-[9px] opacity-70">↗</span>
            </span>
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-2xl sm:text-3xl font-black text-[#38bdf8] tracking-tight">{queueRemaining}</span>
            <span className="text-[11px] font-medium text-cyan-400/80">Active queue</span>
          </div>

          {/* Mini Sparkline SVG */}
          <div className="mt-2 h-6 w-full opacity-60 group-hover:opacity-100 transition-opacity">
            <svg className="w-full h-full" viewBox="0 0 120 24" preserveAspectRatio="none">
              <path
                d="M0 10 Q30 16 60 8 T120 18"
                fill="none"
                stroke="#38bdf8"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
        </div>
      </div>

      {/* Detail Drilldown Modal */}
      {activeModalCategory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-fadeIn">
          <div className="relative w-full max-w-4xl max-h-[85vh] rounded-3xl border border-white/10 bg-[#090f18] p-6 shadow-2xl flex flex-col space-y-4 text-slate-200">
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-white/10">
              <div className="flex items-center gap-3">
                <span
                  style={{
                    background:
                      activeModalCategory === "SUBMITTED"
                        ? "rgba(46, 232, 201, 0.15)"
                        : activeModalCategory === "STAGED"
                        ? "rgba(245, 158, 11, 0.15)"
                        : activeModalCategory === "SKIPPED"
                        ? "rgba(99, 102, 241, 0.15)"
                        : activeModalCategory === "FAILED"
                        ? "rgba(244, 63, 94, 0.15)"
                        : "rgba(56, 189, 248, 0.15)",
                    color:
                      activeModalCategory === "SUBMITTED"
                        ? "#2ee8c9"
                        : activeModalCategory === "STAGED"
                        ? "#f59e0b"
                        : activeModalCategory === "SKIPPED"
                        ? "#818cf8"
                        : activeModalCategory === "FAILED"
                        ? "#f43f5e"
                        : "#38bdf8",
                  }}
                  className="px-3 py-1 rounded-full text-xs font-black tracking-wider uppercase border border-current"
                >
                  {activeModalCategory} JOBS ({modalJobs.length})
                </span>
                <span className="text-xs text-slate-400">
                  Full inspection of all target URLs, submission timestamps, and evidence
                </span>
              </div>
              <button
                onClick={() => setActiveModalCategory(null)}
                className="p-1.5 rounded-full hover:bg-white/10 text-slate-400 hover:text-white transition-colors cursor-pointer"
              >
                <IconX className="w-5 h-5" />
              </button>
            </div>

            {/* Content List */}
            <div className="flex-1 overflow-y-auto space-y-3 pr-1">
              {loadingModal ? (
                <div className="p-12 text-center text-xs text-slate-400 font-mono">
                  Loading jobs...
                </div>
              ) : modalJobs.length === 0 ? (
                <div className="p-12 text-center text-xs text-slate-500 border border-dashed border-white/10 rounded-2xl bg-white/[0.02]">
                  No {activeModalCategory.toLowerCase()} applications recorded yet.
                </div>
              ) : (
                modalJobs.map((job) => {
                  const submittedAt = job.submittedAt
                    ? new Date(job.submittedAt).toLocaleString()
                    : null;
                  const queuedAt = job.queuedAt
                    ? new Date(job.queuedAt).toLocaleString()
                    : null;
                  const appUrl = job.applicationUrl || job.listingUrl || "";

                  return (
                    <div
                      key={job.id}
                      className="p-4 rounded-2xl border border-white/10 bg-[#0d1420] hover:border-white/20 transition-all space-y-2.5"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <h4 className="text-sm font-bold text-white flex items-center gap-2">
                            {job.title || "Untitled Role"}
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-[#2ee8c9]/15 text-[#2ee8c9] border border-[#2ee8c9]/30">
                              {job.matchScore}% Match
                            </span>
                          </h4>
                          <p className="text-xs text-slate-400 mt-0.5">{job.company}</p>
                        </div>

                        {appUrl && (
                          <a
                            href={appUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/5 border border-white/10 text-xs font-semibold text-[#38bdf8] hover:bg-[#38bdf8]/10 hover:border-[#38bdf8]/40 transition-all cursor-pointer"
                          >
                            <span>Open Job Link</span>
                            <IconExternalLink className="w-3.5 h-3.5" />
                          </a>
                        )}
                      </div>

                      {/* Timestamps & Evidence Grid */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 text-xs pt-1 border-t border-white/5 font-mono">
                        {submittedAt && (
                          <div className="text-slate-300">
                            <span className="text-slate-500 font-sans block text-[10px] uppercase font-bold">
                              Submitted At
                            </span>
                            {submittedAt}
                          </div>
                        )}

                        {queuedAt && (
                          <div className="text-slate-300">
                            <span className="text-slate-500 font-sans block text-[10px] uppercase font-bold">
                              Queued At
                            </span>
                            {queuedAt}
                          </div>
                        )}

                        {job.lastError && (
                          <div className="text-rose-300 sm:col-span-2">
                            <span className="text-rose-400/80 font-sans block text-[10px] uppercase font-bold">
                              Reason / Blocker
                            </span>
                            {job.lastError}
                          </div>
                        )}

                        {job.submissionEvidence && (
                          <div className="text-emerald-300 sm:col-span-2">
                            <span className="text-emerald-400/80 font-sans block text-[10px] uppercase font-bold">
                              Submission Evidence
                            </span>
                            {typeof job.submissionEvidence === "object"
                              ? job.submissionEvidence.confirmationText || JSON.stringify(job.submissionEvidence)
                              : String(job.submissionEvidence)}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Footer */}
            <div className="pt-2 border-t border-white/10 flex justify-end">
              <button
                onClick={() => setActiveModalCategory(null)}
                className="px-5 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-xs font-bold text-white transition-all cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
