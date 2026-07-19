"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";
import { CoreStatus, getStatusDetails, StatusIndicator } from "../status-helper";

interface AccomplishmentsTabProps {
  accomplishments: Accomplishment[];
  onSelect: (acc: Accomplishment | null) => void;
  selectedAcc: Accomplishment | null;
  onSave: (acc: Accomplishment) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onAnswerQuestion: (qId: string, ans: string) => Promise<void>;
}

export function AccomplishmentsTab({
  accomplishments,
  onSelect,
  selectedAcc,
  onSave,
  onDelete,
  onAnswerQuestion,
}: AccomplishmentsTabProps) {
  const [viewMode, setViewMode] = useState<"card" | "list" | "table" | "kanban">("card");
  const [editorSection, setEditorSection] = useState<string>("context");
  const [editingField, setEditingField] = useState<{ id: string; section: string; key: string } | null>(null);
  const [tempValue, setTempValue] = useState("");
  const [hoveredAccId, setHoveredAccId] = useState<string | null>(null);
  const [activeQId, setActiveQId] = useState<string | null>(null);
  const [ansInput, setAnsInput] = useState("");

  const calculateCompleteness = (acc: Accomplishment) => {
    if (!acc.completenessChecklist) return 0;
    const checklist = acc.completenessChecklist;
    const values = Object.values(checklist);
    const completed = values.filter((v) => v === true).length;
    return Math.round((completed / values.length) * 100);
  };

  // Derive counts for card stacked segmented bar
  const getReadinessCounts = (acc: Accomplishment) => {
    const checklist = acc.completenessChecklist;
    if (!checklist) return { missing: 4, weak: 2, strong: 4, ready: 0 };
    
    let missing = 0;
    let weak = 0;
    let strong = 0;
    let ready = 0;

    // Check ownership
    if (!acc.roleDetails?.ownership) weak += 1;
    else strong += 1;

    // Check scale
    if (!checklist.scaleIncluded) weak += 1;
    else strong += 1;

    // Check architecture
    if (!checklist.architectureExplained) missing += 1;
    else strong += 1;

    // Check evidence
    if (!checklist.evidenceAttached) missing += 1;
    else ready += 1;

    return { missing, weak, strong, ready };
  };

  const handleInlineEditStart = (accId: string, section: string, key: string, val: string) => {
    setEditingField({ id: accId, section, key });
    setTempValue(val);
  };

  const handleInlineSave = async () => {
    if (!editingField || !selectedAcc) return;
    const updated = { ...selectedAcc };
    if (editingField.section === "root") {
      (updated as any)[editingField.key] = tempValue;
    } else {
      (updated as any)[editingField.section] = {
        ...(updated as any)[editingField.section],
        [editingField.key]: tempValue,
      };
    }
    await onSave(updated);
    setEditingField(null);
  };

  // Render sub-sections inside the explorer workspace editor
  const renderEditorContent = () => {
    if (!selectedAcc) return null;

    if (editorSection === "context") {
      return (
        <div className="flex flex-col gap-5 animate-fade-in text-xs">
          <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-800 flex flex-col gap-1.5">
            <span className="text-[10px] font-bold text-slate-500 uppercase">My Responsibility</span>
            {editingField?.key === "responsibility" ? (
              <div className="flex flex-col gap-2">
                <textarea
                  rows={3}
                  value={tempValue}
                  onChange={(e) => setTempValue(e.target.value)}
                  className="w-full p-2 rounded bg-slate-900 border border-slate-850 text-slate-200"
                />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setEditingField(null)} className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700">Cancel</button>
                  <button onClick={handleInlineSave} className="px-2.5 py-1 rounded bg-violet-600 hover:bg-violet-500 font-semibold text-white">Save</button>
                </div>
              </div>
            ) : (
              <p
                onClick={() => handleInlineEditStart(selectedAcc.id, "roleDetails", "responsibility", selectedAcc.roleDetails?.responsibility || "")}
                className="text-slate-200 cursor-pointer hover:bg-slate-900/40 p-1.5 rounded transition"
              >
                {selectedAcc.roleDetails?.responsibility || "Click to add responsibility description..."}
              </p>
            )}
          </div>

          <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-800 flex flex-col gap-1.5">
            <span className="text-[10px] font-bold text-slate-500 uppercase">What Problem Existed?</span>
            {editingField?.key === "what" ? (
              <div className="flex flex-col gap-2">
                <textarea
                  rows={3}
                  value={tempValue}
                  onChange={(e) => setTempValue(e.target.value)}
                  className="w-full p-2 rounded bg-slate-900 border border-slate-850 text-slate-200"
                />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setEditingField(null)} className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700">Cancel</button>
                  <button onClick={handleInlineSave} className="px-2.5 py-1 rounded bg-violet-600 hover:bg-violet-500 font-semibold text-white">Save</button>
                </div>
              </div>
            ) : (
              <p
                onClick={() => handleInlineEditStart(selectedAcc.id, "problemContext", "what", selectedAcc.problemContext?.what || "")}
                className="text-slate-200 cursor-pointer hover:bg-slate-900/40 p-1.5 rounded transition"
              >
                {selectedAcc.problemContext?.what || "Describe what the problem context was..."}
              </p>
            )}
          </div>
        </div>
      );
    }

    if (editorSection === "decisions") {
      return (
        <div className="flex flex-col gap-5 animate-fade-in text-xs">
          <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-800 flex flex-col gap-1.5">
            <span className="text-[10px] font-bold text-slate-500 uppercase">Architectural Decisions Made</span>
            {editingField?.key === "decisionsWhat" ? (
              <div className="flex flex-col gap-2">
                <textarea
                  rows={3}
                  value={tempValue}
                  onChange={(e) => setTempValue(e.target.value)}
                  className="w-full p-2 rounded bg-slate-900 border border-slate-850 text-slate-200"
                />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setEditingField(null)} className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700">Cancel</button>
                  <button onClick={handleInlineSave} className="px-2.5 py-1 rounded bg-violet-600 hover:bg-violet-500 font-semibold text-white">Save</button>
                </div>
              </div>
            ) : (
              <p
                onClick={() => handleInlineEditStart(selectedAcc.id, "decisions", "what", selectedAcc.decisions?.what || "")}
                className="text-slate-200 cursor-pointer hover:bg-slate-900/40 p-1.5 rounded transition"
              >
                {selectedAcc.decisions?.what || "Click to add decisions..."}
              </p>
            )}
          </div>

          <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-800 flex flex-col gap-1.5">
            <span className="text-[10px] font-bold text-slate-500 uppercase">Tradeoffs Considered</span>
            {editingField?.key === "tradeoffs" ? (
              <div className="flex flex-col gap-2">
                <textarea
                  rows={3}
                  value={tempValue}
                  onChange={(e) => setTempValue(e.target.value)}
                  className="w-full p-2 rounded bg-slate-900 border border-slate-850 text-slate-200"
                />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setEditingField(null)} className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700">Cancel</button>
                  <button onClick={handleInlineSave} className="px-2.5 py-1 rounded bg-violet-600 hover:bg-violet-500 font-semibold text-white">Save</button>
                </div>
              </div>
            ) : (
              <p
                onClick={() => handleInlineEditStart(selectedAcc.id, "decisions", "tradeoffs", selectedAcc.decisions?.tradeoffs || "")}
                className="text-slate-200 cursor-pointer hover:bg-slate-900/40 p-1.5 rounded transition"
              >
                {selectedAcc.decisions?.tradeoffs || "Describe tradeoffs considered..."}
              </p>
            )}
          </div>
        </div>
      );
    }

    if (editorSection === "systemDesign") {
      return (
        <div className="flex flex-col gap-5 animate-fade-in text-xs">
          <div className="p-4 rounded-lg bg-slate-950/40 border border-slate-800 flex flex-col gap-1.5">
            <span className="text-[10px] font-bold text-slate-500 uppercase">Data Flow & Sequences</span>
            <p className="text-slate-300 italic">{selectedAcc.systemDesign?.dataFlow || "No data flow written."}</p>
          </div>
        </div>
      );
    }

    if (editorSection === "metrics") {
      return (
        <div className="flex flex-col gap-3 animate-fade-in text-xs">
          {selectedAcc.scaleMetrics?.map((m, i) => (
            <div key={i} className="flex justify-between items-center p-3 rounded-lg bg-slate-950/40 border border-slate-800">
              <span className="font-bold text-slate-300">{m.metric}</span>
              <span className="bg-violet-950/50 border border-violet-900/30 text-violet-400 font-bold px-2 py-0.5 rounded text-[11px]">{m.value}</span>
            </div>
          ))}
        </div>
      );
    }

    if (editorSection === "gaps") {
      const gapsList = [
        { id: "problem", category: "Problem context", status: selectedAcc.completenessChecklist?.problemExplained ? "strong" : "missing", missingText: "Missing explanation of the business problem context.", action: "Explain the underlying business problem why this project mattered." },
        { id: "ownership", category: "Personal ownership", status: selectedAcc.roleDetails?.ownership ? "strong" : "weak", missingText: "Ownership model is generic or unclear.", action: "Specify whether you were the primary lead, architect, or author." },
        { id: "architecture", category: "System Architecture", status: selectedAcc.completenessChecklist?.architectureExplained ? "strong" : "missing", missingText: "System architecture decisions are not fully documented.", action: "List the components and reasons why this design was selected." },
        { id: "evidence", category: "Linked Evidence", status: selectedAcc.completenessChecklist?.evidenceAttached ? "ready" : "weak", missingText: "No linked RFCs, PRs, or telemetry dashboards.", action: "Attach design document URLs or commit histories." },
      ];

      return (
        <div className="flex flex-col gap-4 animate-fade-in text-xs">
          <span className="text-[10px] font-bold text-slate-500 uppercase block mb-1">What is missing from this bullet?</span>
          {gapsList.map(gap => {
            const details = getStatusDetails(gap.status as CoreStatus);
            return (
              <div key={gap.id} className="p-4 rounded-lg bg-slate-950/40 border border-slate-800 flex flex-col gap-2">
                <div className="flex justify-between items-center">
                  <span className="font-bold text-slate-200">{gap.category}</span>
                  <StatusIndicator status={gap.status as CoreStatus} />
                </div>
                {gap.status !== "strong" && gap.status !== "ready" && (
                  <p className="text-slate-400 mt-1 leading-relaxed">
                    <strong>Gap:</strong> {gap.missingText} <br />
                    <span className="text-violet-400">Next Action: {gap.action}</span>
                  </p>
                )}
              </div>
            );
          })}
        </div>
      );
    }

    return null;
  };

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      {!selectedAcc ? (
        <>
          {/* View Toolbar */}
          <div className="flex justify-between items-center border-b border-slate-800 pb-3">
            <div className="text-xs font-semibold text-slate-400">Accomplishments Explorer</div>
            <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-md border border-slate-800/80">
              {(["card", "list", "table", "kanban"] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  className={`px-2.5 py-1 rounded text-[10px] font-bold capitalize transition ${
                    viewMode === mode
                      ? "bg-slate-800 text-violet-400"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {mode}
                </button>
              ))}
            </div>
          </div>

          {/* Explorer Views */}
          {viewMode === "card" && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {accomplishments.map((acc) => {
                const isHovered = hoveredAccId === acc.id;
                const readiness = getReadinessCounts(acc);
                return (
                  <div
                    key={acc.id}
                    onClick={() => onSelect(acc)}
                    onMouseEnter={() => setHoveredAccId(acc.id)}
                    onMouseLeave={() => setHoveredAccId(null)}
                    className="p-5 rounded-xl border border-slate-800 bg-slate-900/20 hover:bg-slate-900/40 hover:border-slate-700/80 transition cursor-pointer relative group flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex justify-between items-start">
                        <span className="text-[10px] font-bold text-violet-400 uppercase tracking-wide">{acc.company}</span>
                        <span className="text-[9px] bg-slate-850 px-1.5 py-0.5 rounded text-slate-400 border border-slate-800">{calculateCompleteness(acc)}% complete</span>
                      </div>
                      <h4 className="text-sm font-bold mt-2 text-white group-hover:text-violet-400 transition">{acc.project}</h4>
                      <p className="text-xs text-slate-400 mt-1 line-clamp-2 leading-relaxed">
                        {acc.resumeEvolution?.current || acc.problemContext?.what}
                      </p>
                    </div>

                    {/* Compact Segmented Readiness Bar */}
                    <div className="mt-4 flex flex-col gap-1.5">
                      <div className="w-full bg-slate-900 h-1.5 rounded-full overflow-hidden flex">
                        <div className="bg-green-500 h-full" style={{ width: `${(readiness.strong / 10) * 100}%` }}></div>
                        <div className="bg-emerald-400 h-full" style={{ width: `${(readiness.ready / 10) * 100}%` }}></div>
                        <div className="bg-amber-500 h-full" style={{ width: `${(readiness.weak / 10) * 100}%` }}></div>
                        <div className="bg-red-500 h-full" style={{ width: `${(readiness.missing / 10) * 100}%` }}></div>
                      </div>
                      <div className="flex justify-between text-[9px] text-slate-500 font-semibold">
                        <span>{readiness.missing} gaps</span>
                        <span>{readiness.weak} need detail</span>
                        <span>{readiness.strong + readiness.ready} strong</span>
                      </div>
                    </div>

                    {/* Popover Preview */}
                    {isHovered && (
                      <div className="absolute top-full left-0 right-0 z-10 mt-1 p-3.5 rounded-lg border border-slate-800 bg-slate-950 shadow-xl text-[10px] flex flex-col gap-1.5 animate-fade-in">
                        <div><strong className="text-slate-400">Why it matters:</strong> {acc.problemContext?.why}</div>
                        <div><strong className="text-slate-400">Principal Concern:</strong> {acc.reviews?.principal?.architectureConcerns?.[0] || "None flagged."}</div>
                        <div><strong className="text-violet-400">Recommendation:</strong> {acc.roadmap?.top3Improvements?.[0]}</div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {viewMode === "list" && (
            <div className="flex flex-col gap-2">
              {accomplishments.map((acc) => (
                <div
                  key={acc.id}
                  onClick={() => onSelect(acc)}
                  className="p-3.5 rounded-lg border border-slate-800/80 bg-slate-900/10 hover:bg-slate-900/30 transition cursor-pointer flex justify-between items-center text-xs"
                >
                  <div>
                    <span className="text-[9px] font-bold text-slate-500 uppercase mr-3">{acc.company}</span>
                    <span className="font-bold text-slate-200">{acc.project}</span>
                  </div>
                  <span className="text-[10px] text-violet-400 font-semibold">{calculateCompleteness(acc)}% complete</span>
                </div>
              ))}
            </div>
          )}

          {viewMode === "table" && (
            <div className="overflow-x-auto border border-slate-800 rounded-xl bg-slate-950/40">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/40 text-slate-400 font-semibold">
                    <th className="p-3">Company</th>
                    <th className="p-3">Project</th>
                    <th className="p-3">Period</th>
                    <th className="p-3">Resistance Score</th>
                    <th className="p-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {accomplishments.map((acc) => (
                    <tr
                      key={acc.id}
                      onClick={() => onSelect(acc)}
                      className="border-b border-slate-850 hover:bg-slate-900/20 cursor-pointer transition"
                    >
                      <td className="p-3 font-semibold text-slate-400">{acc.company}</td>
                      <td className="p-3 font-bold text-slate-200">{acc.project}</td>
                      <td className="p-3 text-slate-400">{acc.timePeriod}</td>
                      <td className="p-3 text-violet-400 font-black">{acc.roastResistanceScore || 0}/100</td>
                      <td className="p-3">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded capitalize ${
                          acc.completenessStatus === "Complete"
                            ? "bg-green-950/40 text-green-400 border border-green-900/20"
                            : "bg-amber-950/40 text-amber-400 border border-amber-900/20"
                        }`}>
                          {acc.completenessStatus || "Incomplete"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {viewMode === "kanban" && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {["Complete", "Needs information", "Incomplete"].map((status) => {
                const groupAccs = accomplishments.filter(a => (a.completenessStatus || "Incomplete") === status);
                return (
                  <div key={status} className="p-4 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-3">
                    <div className="flex justify-between items-center border-b border-slate-850 pb-2">
                      <span className="text-[10px] font-black uppercase tracking-wider text-slate-400">{status}</span>
                      <span className="bg-slate-900 text-slate-400 px-1.5 py-0.5 rounded text-[10px] font-bold">{groupAccs.length}</span>
                    </div>
                    <div className="flex flex-col gap-2">
                      {groupAccs.map((acc) => (
                        <div
                          key={acc.id}
                          onClick={() => onSelect(acc)}
                          className="p-3 rounded-lg border border-slate-800 bg-slate-950 hover:bg-slate-900/40 transition cursor-pointer text-xs"
                        >
                          <span className="text-[9px] font-bold text-violet-400 uppercase">{acc.company}</span>
                          <h5 className="font-bold text-slate-200 mt-1">{acc.project}</h5>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      ) : (
        /* Accomplishment Split Workspace Editor */
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-fade-in items-start">
          {/* Left panel outline */}
          <div className="lg:col-span-3 p-4 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-1.5">
            <button
              onClick={() => onSelect(null)}
              className="text-[10px] font-bold uppercase text-slate-500 hover:text-slate-300 tracking-wider mb-2 text-left"
            >
              ← Back to List
            </button>
            <div className="flex flex-col gap-1">
              {[
                { id: "context", label: "Context & Description" },
                { id: "decisions", label: "Architecture Decisions" },
                { id: "systemDesign", label: "System Design Data" },
                { id: "metrics", label: "Structured Scale Metrics" },
                { id: "gaps", label: "What is missing?" },
              ].map((sec) => (
                <button
                  key={sec.id}
                  onClick={() => setEditorSection(sec.id)}
                  className={`w-full text-left px-3 py-2 rounded text-xs font-semibold transition ${
                    editorSection === sec.id
                      ? "bg-slate-800 text-violet-400 border border-slate-700/50"
                      : "text-slate-400 hover:bg-slate-800/40"
                  }`}
                >
                  {sec.label}
                </button>
              ))}
            </div>
          </div>

          {/* Center outline editor content */}
          <div className="lg:col-span-5 flex flex-col gap-6">
            <div className="border-b border-slate-800 pb-3">
              <span className="text-xs font-bold text-violet-400 uppercase tracking-widest">{selectedAcc.company}</span>
              <h3 className="text-base font-bold mt-1 text-white">{selectedAcc.project}</h3>
            </div>
            {renderEditorContent()}
          </div>

          {/* Right outline reviewer audits & gaps panel */}
          <div className="lg:col-span-4 p-4 rounded-xl border border-slate-800 bg-slate-950/40 flex flex-col gap-4">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-2">Audits & Gaps</h4>

            {/* Unanswered Gaps Q&A block */}
            <div className="flex flex-col gap-2">
              <span className="text-[10px] font-bold text-violet-400 uppercase">Reviewer Gap Questions</span>
              {selectedAcc.missingQuestions && selectedAcc.missingQuestions.length > 0 ? (
                selectedAcc.missingQuestions.map((q) => (
                  <div key={q.id} className="p-3 rounded bg-slate-900 border border-slate-850 text-xs flex flex-col gap-2">
                    <div className="flex justify-between items-start gap-2">
                      <span className="font-medium text-slate-300">{q.question}</span>
                      {!q.answer && activeQId !== q.id && (
                        <button
                          onClick={() => {
                            setActiveQId(q.id);
                            setAnsInput("");
                          }}
                          className="text-[10px] text-violet-400 font-bold hover:underline"
                        >
                          Answer
                        </button>
                      )}
                    </div>
                    {q.answer && (
                      <p className="text-[11px] text-slate-400 italic bg-slate-950 p-2 rounded border border-slate-850 mt-1">
                        <strong>Ans:</strong> {q.answer}
                      </p>
                    )}
                    {activeQId === q.id && (
                      <div className="flex flex-col gap-1.5 mt-2">
                        <textarea
                          rows={2}
                          value={ansInput}
                          onChange={(e) => setAnsInput(e.target.value)}
                          placeholder="Type technical answer details..."
                          className="w-full p-2 bg-slate-950 border border-slate-800 rounded text-slate-200 text-xs focus:outline-none"
                        />
                        <div className="flex justify-end gap-1.5">
                          <button onClick={() => setActiveQId(null)} className="px-2 py-0.5 rounded bg-slate-800 text-[10px]">Cancel</button>
                          <button
                            onClick={async () => {
                              await onAnswerQuestion(q.id, ansInput);
                              setActiveQId(null);
                            }}
                            className="px-2.5 py-0.5 rounded bg-violet-600 font-semibold text-white text-[10px]"
                          >
                            Save
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))
              ) : (
                <div className="text-[10px] text-slate-500 italic">No gap questions compiled.</div>
              )}
            </div>

            {/* Overall roast overview summary */}
            {selectedAcc.reviews?.devil?.overallRoast && (
              <div className="p-3 rounded bg-red-950/20 border border-red-900/20 text-xs text-red-300 leading-normal">
                <strong className="text-[10px] font-bold text-red-400 block mb-1">Devil's Advocate roast:</strong>
                "{selectedAcc.reviews.devil.overallRoast}"
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
