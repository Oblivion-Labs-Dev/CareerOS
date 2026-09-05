"use client";

import React from "react";
import { SubmissionReceiptItem } from "@/lib/application-assistant-api";
import { IconCheckCircle } from "./autopilot/icons";

interface SubmissionReceiptModalProps {
  receipt: SubmissionReceiptItem;
  onClose: () => void;
}

export function SubmissionReceiptModal({ receipt, onClose }: SubmissionReceiptModalProps) {
  const downloadReceiptJson = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(receipt, null, 2));
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `submission_receipt_${receipt.jobId}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-3xl max-h-[90vh] flex flex-col rounded-2xl bg-[#090d12] border border-emerald-500/30 shadow-[0_0_50px_rgba(46,232,201,0.15)] text-slate-100 overflow-hidden font-sans">
        {/* Header Certificate Ribbon */}
        <div className="p-6 border-b border-white/10 bg-gradient-to-r from-[#0a1815] via-[#0d221e] to-[#071310] flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center shadow-[0_0_20px_rgba(46,232,201,0.3)]">
              <IconCheckCircle className="w-7 h-7 text-[#2ee8c9]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-[#2ee8c9] border border-emerald-500/40 uppercase tracking-wider">
                  Verified Submission Receipt
                </span>
                <span className="text-xs text-slate-400 font-mono">
                  {receipt.receiptId}
                </span>
              </div>
              <h2 className="text-lg font-bold text-white mt-0.5">
                {receipt.title} <span className="text-slate-400 font-normal">@</span> <span className="text-[#2ee8c9]">{receipt.company}</span>
              </h2>
            </div>
          </div>

          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-2 rounded-xl bg-white/5 hover:bg-white/10 transition-all cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Receipt Details Body */}
        <div className="flex-1 p-6 overflow-y-auto space-y-5 text-xs">
          {/* Metadata Matrix */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3 rounded-xl bg-white/5 border border-white/5">
              <span className="text-slate-400 block text-[10px] uppercase font-semibold">Timestamp</span>
              <span className="text-slate-200 font-medium font-mono">{receipt.submittedAt?.replace("T", " ").slice(0, 19)} UTC</span>
            </div>
            <div className="p-3 rounded-xl bg-white/5 border border-white/5">
              <span className="text-slate-400 block text-[10px] uppercase font-semibold">Fields Filled</span>
              <span className="text-[#2ee8c9] font-bold text-sm">{receipt.fieldsCount} Inputs</span>
            </div>
            <div className="p-3 rounded-xl bg-white/5 border border-white/5">
              <span className="text-slate-400 block text-[10px] uppercase font-semibold">Status</span>
              <span className="text-emerald-300 font-bold">{receipt.verificationStatus}</span>
            </div>
            <div className="p-3 rounded-xl bg-white/5 border border-white/5">
              <span className="text-slate-400 block text-[10px] uppercase font-semibold">Hash Proof</span>
              <span className="text-purple-300 font-mono text-[10px] truncate block" title={receipt.certificateFingerprint}>
                {receipt.certificateFingerprint?.slice(0, 10)}...
              </span>
            </div>
            {receipt.tailoringMode && (
              <div className="p-3 rounded-xl bg-white/5 border border-white/5">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Resume Used</span>
                <span className="text-amber-300 font-bold text-sm">{receipt.tailoringMode.toUpperCase()}</span>
                {receipt.resumeFileUsed && (
                  <span className="text-slate-500 font-mono text-[10px] truncate block">{receipt.resumeFileUsed}</span>
                )}
              </div>
            )}
            {receipt.matchScoreAtSubmission != null && (
              <div className="p-3 rounded-xl bg-white/5 border border-white/5">
                <span className="text-slate-400 block text-[10px] uppercase font-semibold">Match Score</span>
                <span className="text-emerald-300 font-bold text-sm">{Math.round(receipt.matchScoreAtSubmission)}%</span>
              </div>
            )}
          </div>

          {/* Confirmation Message */}
          <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-500/20 space-y-1">
            <span className="text-emerald-400 font-bold block uppercase text-[10px]">ATS Confirmation Response</span>
            <p className="text-slate-200 leading-relaxed font-medium">"{receipt.confirmationText}"</p>
          </div>

          {/* Form Fields Archive Log */}
          <div className="space-y-2">
            <span className="text-slate-400 font-bold uppercase tracking-wider text-[10px] block">
              Exact Form Fields & Answers Submitted
            </span>
            <div className="rounded-xl border border-white/10 bg-slate-950/60 divide-y divide-white/5 max-h-56 overflow-y-auto">
              {Object.entries(receipt.fieldsFilled || {}).map(([key, val], idx) => (
                <div key={idx} className="p-2.5 flex items-center justify-between gap-4">
                  <span className="text-slate-400 font-medium truncate max-w-[280px]">{key}</span>
                  <span className="text-slate-100 font-mono truncate max-w-[320px] bg-white/5 px-2 py-0.5 rounded border border-white/5">
                    {String(val)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Actions Footer */}
        <div className="p-4 border-t border-white/10 bg-[#070b0f] flex items-center justify-between">
          <span className="text-[11px] text-slate-500 font-mono">
            Cryptographically sealed receipt. Retain for compliance audit.
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={downloadReceiptJson}
              className="px-4 py-1.5 text-xs font-semibold text-emerald-300 hover:text-emerald-200 bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 rounded-xl transition-all cursor-pointer flex items-center gap-1.5"
            >
              <span>📥</span>
              <span>Download Receipt JSON</span>
            </button>
            <button
              onClick={onClose}
              className="px-4 py-1.5 text-xs font-semibold text-slate-300 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl transition-all cursor-pointer"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
