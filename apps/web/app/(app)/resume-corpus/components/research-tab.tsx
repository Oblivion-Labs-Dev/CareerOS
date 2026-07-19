"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";

interface ResearchTabProps {
  accomplishments: Accomplishment[];
}

interface ResearchItem {
  id: string;
  project: string;
  fact: string;
  whyItMatters: string;
  source: string;
  priority: "high" | "medium";
  status: "unresolved" | "found" | "verified";
}

export function ResearchTab({ accomplishments }: ResearchTabProps) {
  const [researchList, setResearchList] = useState<ResearchItem[]>([
    { id: "1", project: "Edge Gateway", fact: "Confirm daily replay packet volume", whyItMatters: "Validates peak TPS claims in resume", source: "DataDog Dashboard", priority: "high", status: "unresolved" },
    { id: "2", project: "Auth Pipeline", fact: "Find Prime Day peak request count", whyItMatters: "Adds scale metrics to recruiter pitch", source: "Launch Review Document", priority: "high", status: "unresolved" },
    { id: "3", project: "Canary Releases", fact: "Verify number of adopting tenant teams", whyItMatters: "Proves cross-team impact and leadership", source: "Promotion proposal RFCs", priority: "medium", status: "found" },
  ]);

  const [newFact, setNewFact] = useState("");
  const [newProj, setNewProj] = useState("");
  const [newSource, setNewSource] = useState("");

  const handleAddTask = () => {
    if (!newFact.trim() || !newProj.trim()) return;
    const item: ResearchItem = {
      id: Date.now().toString(),
      project: newProj,
      fact: newFact,
      whyItMatters: "Substantiates metrics and ownership for target descriptions",
      source: newSource || "Engineering Logs / RFCs",
      priority: "medium",
      status: "unresolved",
    };
    setResearchList([...researchList, item]);
    setNewFact("");
    setNewProj("");
    setNewSource("");
  };

  const handleUpdateStatus = (id: string, nextStatus: "unresolved" | "found" | "verified") => {
    setResearchList(prev => prev.map(item => item.id === id ? { ...item, status: nextStatus } : item));
  };

  // Compile Priority Engine list (next highest-value questions)
  const priorityQuestions: { question: string; project: string; why: string }[] = [];
  accomplishments.slice(0, 3).forEach(acc => {
    acc.missingQuestions?.slice(0, 1).forEach(q => {
      priorityQuestions.push({
        question: q.question,
        project: acc.project,
        why: `Resolves missing details in ${q.category}`,
      });
    });
  });

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Research Queue & Priority Engine</h3>
          <p className="text-xs text-slate-500 mt-0.5">Track facts to confirm, metrics to validate, and high-priority questions to resolve.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left: Highest value actions list (Priority Engine) */}
        <div className="lg:col-span-5 p-5 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <span className="text-xs">🔥</span>
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Highest-Value Gaps To Solve Next</h4>
          </div>

          <div className="flex flex-col gap-3">
            {priorityQuestions.length === 0 ? (
              <div className="text-xs text-slate-500 italic py-4">No high-priority questions remain unanswered.</div>
            ) : (
              priorityQuestions.slice(0, 3).map((pq, idx) => (
                <div key={idx} className="p-3.5 rounded-lg bg-slate-950 border border-slate-850 flex flex-col gap-2">
                  <div className="flex justify-between items-center text-[10px]">
                    <span className="font-bold text-violet-400 uppercase">{pq.project}</span>
                    <span className="text-slate-500 font-bold">Priority: High</span>
                  </div>
                  <p className="text-xs text-slate-200 leading-normal font-semibold">"{pq.question}"</p>
                  <span className="text-[10px] text-slate-400 italic">💡 Benefit: {pq.why}</span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right: Research Queue */}
        <div className="lg:col-span-7 flex flex-col gap-4">
          <div className="p-5 rounded-xl border border-slate-800 bg-slate-905 flex flex-col gap-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">Log Research Task</h4>
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div className="flex flex-col gap-1">
                <label className="text-[10px] font-bold text-slate-500 uppercase">Fact to verify</label>
                <input
                  type="text"
                  placeholder="e.g. Confirm peak throughput TPS"
                  value={newFact}
                  onChange={(e) => setNewFact(e.target.value)}
                  className="px-3 py-1.5 rounded bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[10px] font-bold text-slate-500 uppercase">Related Project</label>
                <input
                  type="text"
                  placeholder="e.g. Edge Gateway"
                  value={newProj}
                  onChange={(e) => setNewProj(e.target.value)}
                  className="px-3 py-1.5 rounded bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none"
                />
              </div>
            </div>
            <div className="flex flex-col gap-1 text-xs">
              <label className="text-[10px] font-bold text-slate-500 uppercase">Where to look (Source)</label>
              <input
                type="text"
                placeholder="e.g. DataDog dashboard / RFC section 4"
                value={newSource}
                onChange={(e) => setNewSource(e.target.value)}
                className="px-3 py-1.5 rounded bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none"
              />
            </div>
            <button
              onClick={handleAddTask}
              className="py-1.5 rounded bg-violet-600 hover:bg-violet-500 font-bold text-xs text-white transition self-end px-4"
            >
              Add Task
            </button>
          </div>

          {/* Research tasks list */}
          <div className="flex flex-col gap-3">
            {researchList.map(task => (
              <div key={task.id} className="p-4 rounded-xl border border-slate-800 bg-slate-900/10 flex justify-between items-center text-xs">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${
                      task.status === "verified" ? "bg-green-500" : task.status === "found" ? "bg-amber-500" : "bg-red-500"
                    }`}></span>
                    <span className="font-bold text-slate-200">{task.fact}</span>
                  </div>
                  <span className="text-[10px] text-slate-500 block mt-1 font-semibold">Project: {task.project} • Source: {task.source}</span>
                </div>

                <div className="flex items-center gap-2">
                  <select
                    value={task.status}
                    onChange={(e) => handleUpdateStatus(task.id, e.target.value as any)}
                    className="bg-slate-900 border border-slate-800 rounded px-2 py-0.5 text-[10px] text-slate-300"
                  >
                    <option value="unresolved">Unresolved</option>
                    <option value="found">Found</option>
                    <option value="verified">Verified</option>
                  </select>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
