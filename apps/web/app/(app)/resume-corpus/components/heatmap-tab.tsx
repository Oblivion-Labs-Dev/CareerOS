"use client";

import React from "react";
import { Accomplishment } from "../types";
import { CoreStatus, getStatusDetails } from "../status-helper";

interface HeatmapTabProps {
  accomplishments: Accomplishment[];
  onSelectCell: (acc: Accomplishment, category: string) => void;
}

export function HeatmapTab({ accomplishments, onSelectCell }: HeatmapTabProps) {
  const columns = [
    { id: "ownership", label: "Ownership" },
    { id: "architecture", label: "Architecture" },
    { id: "scale", label: "Scale" },
    { id: "impact", label: "Impact" },
    { id: "leadership", label: "Leadership" },
    { id: "reliability", label: "Reliability" },
    { id: "security", label: "Security" },
    { id: "evidence", label: "Evidence" },
    { id: "interview", label: "Interview" },
    { id: "resume", label: "Resume" },
  ];

  // Helper to derive cell status dynamically
  const getCellStatus = (acc: Accomplishment, colId: string): CoreStatus => {
    const checklist = acc.completenessChecklist;
    if (!checklist) return "missing";

    switch (colId) {
      case "ownership":
        return acc.roleDetails?.ownership ? "strong" : "weak";
      case "architecture":
        return checklist.architectureExplained ? "strong" : "missing";
      case "scale":
        return checklist.scaleIncluded ? "strong" : "weak";
      case "impact":
        return checklist.businessImpactShown ? "strong" : "partial";
      case "leadership":
        return checklist.leadershipShown ? "strong" : "na";
      case "reliability":
        return checklist.reliabilityExplained ? "strong" : "partial";
      case "security":
        return checklist.securityExplained ? "strong" : "na";
      case "evidence":
        return checklist.evidenceAttached ? "ready" : "missing";
      case "interview":
        return checklist.interviewStoryAvailable ? "ready" : "weak";
      case "resume":
        return acc.completenessStatus === "Complete" ? "ready" : "partial";
      default:
        return "na";
    }
  };

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Accomplishment Heatmap Matrix</h3>
          <p className="text-xs text-slate-500 mt-0.5">Global audit grid scoring engineering quality dimensions. Click any cell to resolve gaps.</p>
        </div>
      </div>

      <div className="overflow-x-auto border border-slate-800 rounded-xl bg-slate-950/40">
        <table className="w-full text-left border-collapse text-xs select-none">
          <thead>
            <tr className="border-b border-slate-800 bg-slate-900/40 text-slate-400 font-semibold">
              <th className="p-3 sticky left-0 bg-slate-950/90 backdrop-blur z-10 border-r border-slate-800">Accomplishment</th>
              {columns.map(col => (
                <th key={col.id} className="p-3 text-center min-w-[90px]">{col.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {accomplishments.length === 0 ? (
              <tr>
                <td colSpan={columns.length + 1} className="p-8 text-center text-slate-500 italic">No accomplishments stored.</td>
              </tr>
            ) : (
              accomplishments.map((acc) => (
                <tr key={acc.id} className="border-b border-slate-850 hover:bg-slate-900/10 transition">
                  <td className="p-3 font-bold text-slate-200 sticky left-0 bg-slate-950/90 backdrop-blur z-10 border-r border-slate-800 max-w-[200px] truncate">
                    {acc.project}
                  </td>
                  {columns.map((col) => {
                    const status = getCellStatus(acc, col.id);
                    const details = getStatusDetails(status);
                    return (
                      <td
                        key={col.id}
                        onClick={() => onSelectCell(acc, col.id)}
                        className={`p-3 text-center cursor-pointer transition-all hover:bg-slate-900/30 ${details.bgColorClass}`}
                        title={`${col.label}: ${details.label}`}
                      >
                        <span className="text-base" aria-label={details.label}>{details.icon}</span>
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 p-4 rounded-xl border border-slate-850 bg-slate-900/10 text-[10px] font-semibold">
        {(["missing", "weak", "partial", "strong", "ready", "na", "verify"] as CoreStatus[]).map(st => {
          const det = getStatusDetails(st);
          return (
            <div key={st} className="flex items-center gap-1.5">
              <span>{det.icon}</span>
              <span className="text-slate-300">{det.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
