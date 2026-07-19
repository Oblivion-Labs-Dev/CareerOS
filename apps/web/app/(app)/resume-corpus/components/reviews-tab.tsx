"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";

interface ReviewsTabProps {
  accomplishments: Accomplishment[];
}

export function ReviewsTab({ accomplishments }: ReviewsTabProps) {
  const [selectedAuditor, setSelectedAuditor] = useState<string>("manager");

  const auditors = [
    { id: "manager", label: "Hiring Manager" },
    { id: "principal", label: "Principal Engineer" },
    { id: "devil", label: "Devil's Advocate" },
    { id: "contrarian", label: "Contrarian Reviewer" },
    { id: "recruiter", label: "Recruiter Audit" },
    { id: "ats", label: "ATS Scan" },
    { id: "writer", label: "Resume Writer" },
    { id: "staff", label: "Staff Engineer" },
    { id: "interview", label: "Interview Prep" },
  ];

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex flex-wrap justify-between items-center border-b border-slate-800 pb-3 gap-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Reviewer Intelligence Center</h3>
          <p className="text-xs text-slate-500 mt-0.5">Simulate critical audits from recruiter, writer, ATS, staff and devil's advocates.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left: Auditor profiles selector */}
        <div className="lg:col-span-3 p-4 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-1">
          {auditors.map((auditor) => (
            <button
              key={auditor.id}
              onClick={() => setSelectedAuditor(auditor.id)}
              className={`w-full text-left px-3 py-2 rounded text-xs font-semibold transition ${
                selectedAuditor === auditor.id
                  ? "bg-slate-800 text-violet-400 border border-slate-700/50"
                  : "text-slate-400 hover:bg-slate-800/40"
              }`}
            >
              {auditor.label}
            </button>
          ))}
        </div>

        {/* Right: Reviews lists */}
        <div className="lg:col-span-9 flex flex-col gap-4">
          {accomplishments.length === 0 ? (
            <div className="text-xs text-slate-500 italic py-12 text-center border border-slate-800 border-dashed rounded-lg">
              No accomplishments stored to review.
            </div>
          ) : (
            accomplishments.map((acc) => {
              const reviewObj = (acc.reviews as any)?.[selectedAuditor];
              if (!reviewObj) return null;

              return (
                <div key={acc.id} className="p-5 rounded-xl border border-slate-850 bg-slate-950/40 flex flex-col gap-3">
                  <div className="flex justify-between items-center border-b border-slate-900 pb-2">
                    <span className="text-[10px] font-bold text-violet-400 uppercase tracking-widest">{acc.project} ({acc.company})</span>
                    <span className="text-[10px] text-slate-500 font-semibold">{reviewObj.roleName || "Audit Info"}</span>
                  </div>

                  {selectedAuditor === "manager" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Liked:</strong> {reviewObj.whatLiked?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Average points:</strong> {reviewObj.whatAverage?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Memorable parts:</strong> {reviewObj.whatMemorable?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Concerns:</strong> {reviewObj.concerns?.join(", ") || "None"}</div>
                    </div>
                  )}

                  {selectedAuditor === "principal" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Architecture Concerns:</strong> {reviewObj.architectureConcerns?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">System Design Concerns:</strong> {reviewObj.systemDesignConcerns?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Engineering Depth:</strong> {reviewObj.engineeringDepth || "None"}</div>
                      <div><strong className="text-slate-400">Scalability Concerns:</strong> {reviewObj.scalabilityConcerns?.join(", ") || "None"}</div>
                    </div>
                  )}

                  {selectedAuditor === "devil" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Reasons to Reject:</strong> {reviewObj.reasonsToReject?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Inflated claims:</strong> {reviewObj.reasonsInflated?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Weak wording:</strong> {reviewObj.weakWording?.join(", ") || "None"}</div>
                      <p className="text-xs text-red-400 bg-red-950/20 p-2.5 rounded border border-red-900/20 mt-1 italic">
                        "{reviewObj.overallRoast || "No roast parsed."}"
                      </p>
                    </div>
                  )}

                  {selectedAuditor === "contrarian" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Hidden Assumptions:</strong> {reviewObj.hiddenAssumptions?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Blind Spots:</strong> {reviewObj.blindSpots?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Reduced Credibility reasons:</strong> {reviewObj.reducedCredibilityReasons?.join(", ") || "None"}</div>
                    </div>
                  )}

                  {selectedAuditor === "recruiter" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Survive screening scan:</strong> {reviewObj.surviveScan ? "Yes" : "No"}</div>
                      <div><strong className="text-slate-400">Scannability index:</strong> {reviewObj.scannabilityScore}/100</div>
                      <div><strong className="text-slate-400">Interview probability:</strong> {reviewObj.interviewLikelihood}</div>
                    </div>
                  )}

                  {selectedAuditor === "ats" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Missing keywords:</strong> {reviewObj.missingKeywords?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Ats Score:</strong> {reviewObj.atsScore}/100</div>
                      <div><strong className="text-slate-400">Suggested additions:</strong> {reviewObj.improvements?.join(", ") || "None"}</div>
                    </div>
                  )}

                  {selectedAuditor === "writer" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Weak verbs:</strong> {reviewObj.weakVerbs?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Cliches used:</strong> {reviewObj.cliches?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Alternative wording:</strong> {reviewObj.alternativeWording?.join(", ") || "None"}</div>
                    </div>
                  )}

                  {selectedAuditor === "staff" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Demonstrates System Architecture:</strong> {reviewObj.demonstratesArchitecture ? "Yes" : "No"}</div>
                      <div><strong className="text-slate-400">Demonstrates Ownership:</strong> {reviewObj.demonstratesOwnership ? "Yes" : "No"}</div>
                      <div><strong className="text-slate-400">Demonstrates Leadership:</strong> {reviewObj.demonstratesLeadership ? "Yes" : "No"}</div>
                    </div>
                  )}

                  {selectedAuditor === "interview" && (
                    <div className="flex flex-col gap-2 text-xs text-slate-300">
                      <div><strong className="text-slate-400">Deep Dive Questions:</strong> {reviewObj.questions?.deepDive?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Exposure risks:</strong> {reviewObj.exposureRiskPoints?.join(", ") || "None"}</div>
                      <div><strong className="text-slate-400">Study recommendations:</strong> {reviewObj.topicsToStudy?.join(", ") || "None"}</div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
