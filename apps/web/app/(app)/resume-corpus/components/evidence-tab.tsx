"use client";

import React from "react";
import { Accomplishment } from "../types";

interface EvidenceTabProps {
  accomplishments: Accomplishment[];
}

export function EvidenceTab({ accomplishments }: EvidenceTabProps) {
  // Compile list of evidence items
  const evidenceList: { name: string; url: string; project: string; company: string; type: string }[] = [];
  accomplishments.forEach((acc) => {
    // If the accomplishment has evidence links or simulated items
    if (acc.interviewIntelligence) {
      acc.interviewIntelligence.recruiterPrep?.forEach((q) => {
        if (q.evidence && q.evidence.toLowerCase().includes("http") || q.evidence.toLowerCase().includes("rfc") || q.evidence.toLowerCase().includes("pr")) {
          evidenceList.push({ name: q.evidence, url: "#", project: acc.project, company: acc.company, type: "Document" });
        }
      });
      acc.interviewIntelligence.hmPrep?.forEach((q) => {
        if (q.evidence && q.evidence.toLowerCase().includes("http") || q.evidence.toLowerCase().includes("doc") || q.evidence.toLowerCase().includes("proposal")) {
          evidenceList.push({ name: q.evidence, url: "#", project: acc.project, company: acc.company, type: "Document" });
        }
      });
    }
  });

  // Unique evidence list
  const uniqueEvidence = Array.from(new Set(evidenceList.map(e => e.name))).map(name => {
    return evidenceList.find(e => e.name === name)!;
  });

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Engineering Evidence Vault</h3>
          <p className="text-xs text-slate-500 mt-0.5">Linked design specifications, repositories, pull requests, and telemetry charts verifying claims.</p>
        </div>
      </div>

      {uniqueEvidence.length === 0 ? (
        <div className="text-xs text-slate-500 italic py-12 text-center border border-slate-800 border-dashed rounded-lg">
          No external evidence files linked. Review gap recommendations to attach supporting documents.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {uniqueEvidence.map((ev, idx) => (
            <div
              key={idx}
              className="p-4 rounded-xl border border-slate-800 bg-slate-900/10 hover:bg-slate-900/30 transition flex justify-between items-center text-xs group"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-lg">📁</span>
                  <span className="font-bold text-slate-200 group-hover:text-violet-400 transition">{ev.name}</span>
                </div>
                <span className="text-[10px] text-slate-500 mt-1 block font-semibold">Verified for: {ev.project} ({ev.company})</span>
              </div>
              <span className="text-[10px] font-bold text-violet-400 bg-violet-950/40 border border-violet-900/30 px-2 py-0.5 rounded uppercase tracking-wider">
                {ev.type}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
