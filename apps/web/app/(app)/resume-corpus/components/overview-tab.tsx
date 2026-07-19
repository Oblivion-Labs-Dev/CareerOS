"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";

interface OverviewTabProps {
  accomplishments: Accomplishment[];
  onNavigate: (tab: string) => void;
  onSelectAccomplishment: (acc: Accomplishment) => void;
}

export function OverviewTab({ accomplishments, onNavigate, onSelectAccomplishment }: OverviewTabProps) {
  const [timelineGrouping, setTimelineGrouping] = useState<"company" | "project">("company");

  // Calculate statistics
  const total = accomplishments.length;
  const ready = accomplishments.filter(a => a.completenessStatus === "Complete").length;
  const missingMetrics = accomplishments.reduce((sum, a) => sum + (a.roadmap?.missingMetrics?.length || 0), 0);
  const unansweredQ = accomplishments.reduce((sum, a) => sum + (a.missingQuestions?.filter(q => !q.answer).length || 0), 0);
  
  const calculateCompleteness = (acc: Accomplishment) => {
    if (!acc.completenessChecklist) return 0;
    const checklist = acc.completenessChecklist;
    const values = Object.values(checklist);
    const completed = values.filter((v) => v === true).length;
    return Math.round((completed / values.length) * 100);
  };

  const avgCompleteness = total > 0 
    ? Math.round(accomplishments.reduce((sum, a) => sum + calculateCompleteness(a), 0) / total)
    : 0;

  const avgRoastResistance = total > 0
    ? Math.round(accomplishments.reduce((sum, a) => sum + (a.roastResistanceScore || 0), 0) / total)
    : 0;

  const stats = [
    { label: "Total Accomplishments", value: total, desc: "Structured accomplishments stored", target: "Explore list", action: () => onNavigate("accomplishments") },
    { label: "Resume-Ready", value: ready, desc: "Accomplishments with 100% checklist", target: "Review checklist", action: () => onNavigate("accomplishments") },
    { label: "Missing Metrics", value: missingMetrics, desc: "Opportunities to quantify achievements", target: "Fix metrics", action: () => onNavigate("metrics") },
    { label: "Unanswered Questions", value: unansweredQ, desc: "Gaps identified by LLM reviewers", target: "Answer questions", action: () => onNavigate("accomplishments") },
    { label: "Roast Resistance Avg", value: `${avgRoastResistance}/100`, desc: "Average roast resistance index", target: "Open Reviewer Center", action: () => onNavigate("reviews") },
    { label: "Completeness Avg", value: `${avgCompleteness}%`, desc: "General completeness score", target: "Check details", action: () => onNavigate("accomplishments") },
  ];

  // Derive Priority Actions
  const priorityActions: { text: string; impact: string; action: () => void }[] = [];
  if (unansweredQ > 0) {
    priorityActions.push({ text: "Answer pending technical review questions to resolve design gaps", impact: "High", action: () => onNavigate("accomplishments") });
  }
  if (missingMetrics > 0) {
    priorityActions.push({ text: "Quantify accomplishments by inserting scale, QPS, or cost metrics", impact: "High", action: () => onNavigate("metrics") });
  }
  if (accomplishments.some(a => !a.evidence || a.evidence.length === 0)) {
    priorityActions.push({ text: "Attach evidence files (RFCs, design documents, pull requests) to support claims", impact: "Medium", action: () => onNavigate("accomplishments") });
  }
  priorityActions.push({ text: "Align accomplishments with target job description requirements", impact: "Medium", action: () => onNavigate("match") });

  return (
    <div className="flex flex-col gap-8 animate-fade-in text-slate-100">
      {/* Hero Summary */}
      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/30 flex flex-wrap justify-between items-center gap-6">
        <div>
          <span className="text-[10px] font-bold text-violet-400 uppercase tracking-widest bg-violet-950/40 px-2 py-0.5 rounded border border-violet-900/30">Staff Profile Engine</span>
          <h2 className="text-xl font-bold mt-2">Engineering Portfolio Intelligence</h2>
          <p className="text-xs text-slate-400 mt-1 max-w-lg leading-relaxed">
            Consolidating accomplishments, verified metrics, system design tradeoffs, and reviewer concern feedback to keep your professional corpus ready for any role.
          </p>
        </div>
        <div className="flex items-center gap-6 text-xs border-l border-slate-800 pl-6">
          <div>
            <span className="text-slate-500 block uppercase font-bold text-[9px] tracking-wider">Ready Score</span>
            <span className="text-lg font-black text-violet-400 mt-0.5 block">{avgCompleteness}%</span>
          </div>
          <div>
            <span className="text-slate-500 block uppercase font-bold text-[9px] tracking-wider">Roast resistance</span>
            <span className="text-lg font-black text-emerald-400 mt-0.5 block">{avgRoastResistance}</span>
          </div>
        </div>
      </div>

      {/* Career Health Metrics Cards Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        {stats.map((stat, idx) => (
          <div
            key={idx}
            onClick={stat.action}
            className="p-5 rounded-xl border border-slate-800 bg-slate-950/40 hover:bg-slate-900/40 transition cursor-pointer flex flex-col justify-between min-h-[120px] group"
          >
            <div>
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">{stat.label}</span>
              <div className="text-2xl font-black text-white mt-1 group-hover:text-violet-400 transition">{stat.value}</div>
            </div>
            <div className="flex justify-between items-center mt-3 pt-2 border-t border-slate-900">
              <span className="text-[10px] text-slate-400">{stat.desc}</span>
              <span className="text-[9px] font-bold uppercase tracking-wider text-violet-400 group-hover:underline">→ {stat.target}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Grid: Timeline and Priority Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Timeline */}
        <div className="lg:col-span-2 p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
          <div className="flex justify-between items-center border-b border-slate-800 pb-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Accomplishments Timeline</h3>
            <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-md border border-slate-800/80">
              {(["company", "project"] as const).map((group) => (
                <button
                  key={group}
                  onClick={() => setTimelineGrouping(group)}
                  className={`px-2.5 py-1 rounded text-[10px] font-bold capitalize transition ${
                    timelineGrouping === group
                      ? "bg-slate-800 text-violet-400"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {group}
                </button>
              ))}
            </div>
          </div>

          <div className="relative border-l border-slate-800 pl-4 ml-2 flex flex-col gap-6 py-2">
            {accomplishments.length === 0 ? (
              <div className="text-xs text-slate-500 italic py-6">No accomplishments recorded. Click "+ Record Work" to get started.</div>
            ) : (
              accomplishments.map((acc, idx) => (
                <div
                  key={acc.id || idx}
                  onClick={() => onSelectAccomplishment(acc)}
                  className="relative group cursor-pointer hover:bg-slate-900/10 p-2 rounded-lg transition"
                >
                  {/* Timeline point */}
                  <span className="absolute -left-[21px] top-4 w-2.5 h-2.5 rounded-full bg-violet-600 border border-slate-950 group-hover:bg-violet-400 transition"></span>
                  <div className="text-[10px] text-slate-500 font-semibold">{acc.timePeriod}</div>
                  <h4 className="text-xs font-bold text-slate-200 mt-1 group-hover:text-violet-400 transition">{acc.project}</h4>
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    <span className="text-[9px] bg-slate-900 text-slate-400 px-1.5 py-0.5 rounded border border-slate-850">{timelineGrouping === "company" ? acc.company : acc.project}</span>
                    {acc.techStack?.slice(0, 3).map((t) => (
                      <span key={t} className="text-[9px] bg-slate-900 text-slate-300 px-1.5 py-0.5 rounded border border-slate-850">{t}</span>
                    ))}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Priority Actions */}
        <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-3">Priority Actions</h3>
          <div className="flex flex-col gap-3">
            {priorityActions.map((action, idx) => (
              <div
                key={idx}
                onClick={action.action}
                className="p-3.5 rounded-lg bg-slate-950 border border-slate-850 hover:border-slate-800 transition cursor-pointer flex flex-col gap-2 group"
              >
                <div className="flex justify-between items-center">
                  <span className={`text-[9px] font-black uppercase px-2 py-0.5 rounded tracking-wide ${
                    action.impact === "High"
                      ? "bg-red-950/40 text-red-400 border border-red-900/20"
                      : "bg-amber-950/40 text-amber-400 border border-amber-900/20"
                  }`}>
                    {action.impact} Impact
                  </span>
                  <span className="text-[9px] text-slate-500 font-bold group-hover:underline">Solve →</span>
                </div>
                <p className="text-[11px] text-slate-300 leading-normal group-hover:text-slate-100 font-medium">
                  {action.text}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
