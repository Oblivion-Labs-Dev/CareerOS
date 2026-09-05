"use client";

import React, { useState } from "react";
import {
  TailorDiffResponse,
  approvePreflightSubmission,
  getJobTailorDiff,
  getTailoredResumePdfUrl,
} from "@/lib/application-assistant-api";
import { ResumeDiffViewer } from "./resume-diff-viewer";
import { IconCheckCircle } from "./autopilot/icons";

interface PreflightReviewModalProps {
  diffData: TailorDiffResponse;
  onClose: () => void;
  onSubmitted?: () => void;
}

const TSENTA_MODES: Array<{
  key: "off" | "honest" | "aggressive";
  label: string;
  icon: string;
  badge: string;
  description: string;
}> = [
  {
    key: "off",
    label: "Off",
    icon: "⏹️",
    badge: "No Change",
    description: "Original resume bullets sent as-is. No rewriting or reorganizing.",
  },
  {
    key: "honest",
    label: "Honest",
    icon: "🎯",
    badge: "JD Reorganized",
    description: "Rewriting & reorganizing to match the job description as best as possible from verified experience.",
  },
  {
    key: "aggressive",
    label: "Aggressive",
    icon: "🔥",
    badge: "Inflate & Maximize",
    description: "Inflate scope, metrics, and senior keywords to aggressively match the job description and maximize callback calls.",
  },
];

export function PreflightReviewModal({
  diffData: initialDiffData,
  onClose,
  onSubmitted,
}: PreflightReviewModalProps) {
  const [diffData, setDiffData] = useState<TailorDiffResponse>(initialDiffData);
  const [currentMode, setCurrentMode] = useState<"off" | "honest" | "aggressive">(
    initialDiffData.mode || "honest"
  );
  const [switchingMode, setSwitchingMode] = useState(false);
  const [activeTab, setActiveTab] = useState<"diff" | "cover_letter" | "screening">("diff");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [coverLetter, setCoverLetter] = useState(initialDiffData.tailoredCoverLetter);
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    initialDiffData.screeningQAs.forEach((qa, idx) => {
      map[qa.question] = qa.suggestedAnswer;
    });
    return map;
  });

  const handleModeChange = async (nextMode: "off" | "honest" | "aggressive") => {
    if (nextMode === currentMode || switchingMode) return;
    setCurrentMode(nextMode);
    setSwitchingMode(true);
    setError(null);
    try {
      const res = await getJobTailorDiff(diffData.jobId, nextMode);
      if (res && res.diff) {
        setDiffData(res.diff);
        setCoverLetter(res.diff.tailoredCoverLetter);
        const updatedAnswers: Record<string, string> = {};
        res.diff.screeningQAs.forEach((qa: { question: string; suggestedAnswer: string }) => {
          updatedAnswers[qa.question] = qa.suggestedAnswer;
        });
        setAnswers(updatedAnswers);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to switch tailoring mode");
    } finally {
      setSwitchingMode(false);
    }
  };

  const handleApprove = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await approvePreflightSubmission(diffData.jobId, answers, currentMode);
      setSuccessMsg(res.message || "Submission approved and running in background!");
      setTimeout(() => {
        if (onSubmitted) onSubmitted();
        onClose();
      }, 1500);
    } catch (err: any) {
      setError(err?.message || "Failed to trigger cloud submission");
    } finally {
      setSubmitting(false);
    }
  };

  const activeModeMeta = TSENTA_MODES.find((m) => m.key === currentMode) || TSENTA_MODES[1];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-4xl max-h-[90vh] flex flex-col rounded-2xl bg-[#090d12] border border-cyan-500/30 shadow-[0_0_50px_rgba(0,180,216,0.15)] text-slate-100 overflow-hidden">
        {/* Header Ribbon */}
        <div className="p-6 border-b border-white/10 bg-gradient-to-r from-[#0d1620] to-[#0a1118] flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-cyan-500/15 border border-cyan-500/40 text-cyan-300">
                Tsenta Pre-Flight Checkpoint
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/15 border border-emerald-500/30 text-emerald-400">
                {diffData.matchScore}% Match
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-500/15 border border-purple-500/30 text-purple-300">
                {diffData.visaStatus}
              </span>
              {switchingMode && (
                <span className="text-xs text-amber-400 animate-pulse font-medium">
                  Reorganizing resume…
                </span>
              )}
            </div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2">
              <span>{diffData.title}</span>
              <span className="text-slate-400 font-normal">@</span>
              <span className="text-cyan-300">{diffData.company}</span>
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Salary Target: <span className="text-slate-200 font-medium">{diffData.salaryRange}</span>
            </p>
          </div>

          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-2 rounded-xl bg-white/5 hover:bg-white/10 transition-all cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* 3-Way Tsenta Restructure Dial Bar */}
        <div className="px-6 py-3 border-b border-white/10 bg-[#060a0f] flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
              <span>🛠️</span> Restructure Mode:
            </span>
            <div className="inline-flex rounded-xl bg-slate-900/90 p-1 border border-white/10 shadow-inner">
              {TSENTA_MODES.map((mode) => {
                const isActive = currentMode === mode.key;
                return (
                  <button
                    key={mode.key}
                    type="button"
                    onClick={() => void handleModeChange(mode.key)}
                    disabled={switchingMode}
                    className={`px-3 py-1 text-xs font-bold rounded-lg transition-all cursor-pointer flex items-center gap-1.5 ${
                      isActive
                        ? mode.key === "aggressive"
                          ? "bg-gradient-to-r from-amber-500 to-rose-500 text-slate-950 shadow-[0_0_12px_rgba(245,158,11,0.4)] font-extrabold"
                          : mode.key === "honest"
                          ? "bg-gradient-to-r from-cyan-400 to-teal-400 text-slate-950 shadow-[0_0_12px_rgba(46,232,201,0.35)] font-extrabold"
                          : "bg-slate-700 text-white font-bold"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <span>{mode.icon}</span>
                    <span>{mode.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
          <p className="text-[11px] text-slate-400 max-w-md hidden sm:block">
            <strong className="text-slate-200 font-semibold">{activeModeMeta.label}: </strong>
            {activeModeMeta.description}
          </p>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 px-6 pt-3 border-b border-white/10 bg-[#070b0f]">
          <button
            onClick={() => setActiveTab("diff")}
            className={`pb-3 px-4 text-xs font-bold transition-all border-b-2 cursor-pointer ${
              activeTab === "diff"
                ? "border-cyan-400 text-cyan-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            🔍 Tailored Résumé Diff ({diffData.totalChanges} Changes)
          </button>
          <button
            onClick={() => setActiveTab("cover_letter")}
            className={`pb-3 px-4 text-xs font-bold transition-all border-b-2 cursor-pointer ${
              activeTab === "cover_letter"
                ? "border-cyan-400 text-cyan-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            📄 Tailored Cover Letter
          </button>
          <button
            onClick={() => setActiveTab("screening")}
            className={`pb-3 px-4 text-xs font-bold transition-all border-b-2 cursor-pointer ${
              activeTab === "screening"
                ? "border-cyan-400 text-cyan-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            💡 Screening Q&A Preview ({diffData.screeningQAs.length})
          </button>
        </div>

        {/* Tab Content Body */}
        <div className="flex-1 p-6 overflow-y-auto space-y-4">
          {error && (
            <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
              {error}
            </div>
          )}

          {successMsg && (
            <div className="p-3 rounded-xl bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs flex items-center gap-2">
              <IconCheckCircle className="w-4 h-4" />
              <span>{successMsg}</span>
            </div>
          )}

          {activeTab === "diff" && (
            <ResumeDiffViewer bullets={diffData.bulletDiffs} mode={currentMode} />
          )}

          {activeTab === "cover_letter" && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Role-Aligned Cover Letter
                </span>
                <span className="text-[11px] text-slate-400">Directly editable before submission</span>
              </div>
              <textarea
                rows={12}
                value={coverLetter}
                onChange={(e) => setCoverLetter(e.target.value)}
                className="w-full p-4 rounded-xl bg-slate-950/80 border border-white/10 text-slate-200 text-xs leading-relaxed focus:outline-none focus:border-cyan-400 font-mono"
              />
            </div>
          )}

          {activeTab === "screening" && (
            <div className="space-y-4">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
                Contextual Open-Ended Screening Questions
              </span>
              {diffData.screeningQAs.map((qa, idx) => (
                <div key={idx} className="p-4 rounded-xl bg-slate-900/60 border border-white/10 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-bold text-cyan-200">
                      Q: {qa.question}
                    </p>
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
                      {Math.round(qa.confidence * 100)}% Confidence
                    </span>
                  </div>
                  <textarea
                    rows={3}
                    value={answers[qa.question] || ""}
                    onChange={(e) => setAnswers({ ...answers, [qa.question]: e.target.value })}
                    className="w-full p-2.5 rounded-lg bg-black/50 border border-white/10 text-slate-200 text-xs focus:outline-none focus:border-cyan-400"
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Bottom Actions Bar */}
        <div className="p-5 border-t border-white/10 bg-[#070b0f] flex items-center justify-between gap-4">
          <p className="text-xs text-slate-400">
            Approving triggers cloud stealth submission across ATS fields.
          </p>
          <div className="flex items-center gap-3">
            <a
              href={getTailoredResumePdfUrl(diffData.jobId, currentMode)}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-2 text-xs font-semibold text-cyan-300 hover:text-white rounded-xl bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 transition-all cursor-pointer flex items-center gap-1.5"
              title="Open and download the final rendered 1-page PDF for this mode"
            >
              <span>📄</span>
              <span>View / Download PDF ({currentMode.toUpperCase()})</span>
            </a>
            <button
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-xs font-medium text-slate-400 hover:text-white rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 transition-all cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleApprove}
              disabled={submitting}
              className="px-5 py-2 text-xs font-bold text-black rounded-xl bg-gradient-to-r from-[#2ee8c9] to-cyan-400 hover:from-[#25d3b6] hover:to-cyan-300 shadow-[0_0_20px_rgba(46,232,201,0.4)] transition-all cursor-pointer flex items-center gap-2"
            >
              <span>⚡</span>
              <span>{submitting ? "Initiating Submission..." : "Approve & Cloud Submit"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
