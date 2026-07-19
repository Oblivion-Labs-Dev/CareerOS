"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";

interface BuilderTabProps {
  accomplishments: Accomplishment[];
  generatorInputs: any;
  setGeneratorInputs: (inputs: any) => void;
  generatedResume: any;
  generatingResume: boolean;
  onGenerate: () => Promise<void>;
}

export function BuilderTab({
  accomplishments,
  generatorInputs,
  setGeneratorInputs,
  generatedResume,
  generatingResume,
  onGenerate,
}: BuilderTabProps) {
  const [step, setStep] = useState<number>(1);

  const handleCheckboxChange = (id: string) => {
    const isChecked = generatorInputs.selectedIds.includes(id);
    const nextIds = isChecked
      ? generatorInputs.selectedIds.filter((x: string) => x !== id)
      : [...generatorInputs.selectedIds, id];
    setGeneratorInputs({ ...generatorInputs, selectedIds: nextIds });
  };

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Guided Resume Architect</h3>
          <p className="text-xs text-slate-500 mt-0.5">Synthesize tailored resume bullets dynamically matched to specific roles.</p>
        </div>
        <div className="text-xs font-semibold text-slate-400">Step {step} of 3</div>
      </div>

      {step === 1 && (
        <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-5 max-w-xl animate-fade-in">
          <h4 className="text-sm font-bold text-white">1. Target Job Specifications</h4>
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] font-bold text-slate-500 uppercase">Target Company</label>
            <input
              type="text"
              placeholder="e.g. OpenAI, Stripe, Google"
              value={generatorInputs.targetCompany}
              onChange={(e) => setGeneratorInputs({ ...generatorInputs, targetCompany: e.target.value })}
              className="px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-[10px] font-bold text-slate-500 uppercase">Target Role Title</label>
            <input
              type="text"
              placeholder="e.g. Staff Distributed Systems Engineer"
              value={generatorInputs.targetRole}
              onChange={(e) => setGeneratorInputs({ ...generatorInputs, targetRole: e.target.value })}
              className="px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none"
            />
          </div>
          <button
            onClick={() => setStep(2)}
            disabled={!generatorInputs.targetCompany || !generatorInputs.targetRole}
            className="py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-bold transition-all text-xs"
          >
            Continue
          </button>
        </div>
      )}

      {step === 2 && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-fade-in">
          <div className="lg:col-span-5 p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
            <h4 className="text-sm font-bold text-white">2. Job Description Analysis</h4>
            <div className="flex flex-col gap-1.5">
              <label className="text-[10px] font-bold text-slate-500 uppercase">Job Requirements</label>
              <textarea
                rows={8}
                placeholder="Paste key responsibilities, requirements, and keywords from the job description..."
                value={generatorInputs.jobDescription}
                onChange={(e) => setGeneratorInputs({ ...generatorInputs, jobDescription: e.target.value })}
                className="px-3.5 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none font-mono resize-none"
              />
            </div>
            <div className="flex gap-2">
              <button onClick={() => setStep(1)} className="w-1/2 py-2 rounded-lg bg-slate-800 text-slate-300 text-xs">Back</button>
              <button onClick={() => setStep(3)} className="w-1/2 py-2 rounded-lg bg-violet-600 text-white font-bold text-xs">Next</button>
            </div>
          </div>
          <div className="lg:col-span-7 p-4 rounded-xl border border-slate-800 bg-slate-950/40 text-xs text-slate-300 leading-normal flex flex-col gap-3">
            <h5 className="font-bold text-slate-400 uppercase">Tailoring Guidelines</h5>
            <p>• The generator reads your past engineering accomplishments, decisions, and metrics to optimize bullets for ATS systems and hiring managers.</p>
            <p>• Pasting a detailed job description enables the engine to perform keyword coverage calculations and match required technologies.</p>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-fade-in items-start">
          <div className="lg:col-span-5 p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
            <h4 className="text-sm font-bold text-white">3. Select Accomplishments</h4>
            <div className="flex flex-col gap-2 max-h-[250px] overflow-y-auto border border-slate-800 rounded bg-slate-950 p-2">
              {accomplishments.map((a) => {
                const isChecked = generatorInputs.selectedIds.includes(a.id);
                return (
                  <label key={a.id} className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer hover:text-white p-1 rounded hover:bg-slate-900/30">
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => handleCheckboxChange(a.id)}
                      className="rounded border-slate-800 text-violet-600 focus:ring-violet-500/50"
                    />
                    <span className="truncate">{a.project} at {a.company}</span>
                  </label>
                );
              })}
            </div>
            <div className="flex gap-2">
              <button onClick={() => setStep(2)} className="w-1/2 py-2 rounded bg-slate-800 text-slate-300 text-xs">Back</button>
              <button
                onClick={onGenerate}
                disabled={generatingResume}
                className="w-1/2 py-2 rounded bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-bold text-xs"
              >
                {generatingResume ? "Generating..." : "Assemble Canvas"}
              </button>
            </div>
          </div>

          <div className="lg:col-span-7">
            {generatedResume ? (
              <div className="p-6 rounded-xl border border-slate-800 bg-slate-950 flex flex-col gap-5 shadow-lg">
                <div className="flex justify-between items-center border-b border-slate-850 pb-3">
                  <div>
                    <h5 className="text-sm font-bold text-white">{generatedResume.targetRoleMatched || generatorInputs.targetRole}</h5>
                    <span className="text-[10px] text-slate-500 block">AI Resume Preview Canvas</span>
                  </div>
                  <span className="text-xs font-black text-green-400 bg-green-950/40 border border-green-900/30 px-2 py-0.5 rounded">
                    ATS Match: {generatedResume.atsMatchScore}%
                  </span>
                </div>

                {generatedResume.overallCritique && (
                  <div className="p-3.5 rounded-lg bg-slate-900 border border-slate-850 text-xs text-slate-300 leading-relaxed">
                    <strong className="text-[10px] font-bold uppercase tracking-wider text-violet-400 block mb-1">Formatting Audit</strong>
                    {generatedResume.overallCritique}
                  </div>
                )}

                <div className="flex flex-col gap-3">
                  {generatedResume.resumeBullets?.map((item: any, idx: number) => (
                    <div key={idx} className="p-4 rounded-lg bg-slate-900/30 border border-slate-850 flex flex-col gap-1.5">
                      <div className="flex justify-between text-[10px] font-bold text-slate-400">
                        <span>{item.project}</span>
                        <span>{item.company} — {item.role}</span>
                      </div>
                      <p className="text-xs text-slate-100 font-semibold leading-relaxed mt-1">• {item.optimizedBullet}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 border border-slate-800/60 border-dashed rounded-xl">
                <span className="text-2xl text-slate-600">📄</span>
                <span className="text-slate-500 text-xs mt-2 font-medium">Select accomplishments and click generate to build canvas.</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
