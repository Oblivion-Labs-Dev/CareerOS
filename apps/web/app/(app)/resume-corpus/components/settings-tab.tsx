"use client";

import React from "react";

export function SettingsTab() {
  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Intelligence Configuration Settings</h3>
          <p className="text-xs text-slate-500 mt-0.5">Configure review models, target industries, and LLM evaluator APIs.</p>
        </div>
      </div>

      <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4 max-w-xl">
        <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wide">Evaluator Models</h4>
        <div className="flex flex-col gap-1.5 text-xs">
          <label className="text-[10px] font-bold text-slate-500 uppercase">Primary Evaluator LLM</label>
          <select className="bg-slate-900 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300">
            <option>Google Gemini 2.5 Flash (Default)</option>
            <option>Claude 3.5 Sonnet</option>
            <option>GPT-4o</option>
          </select>
        </div>

        <div className="flex flex-col gap-1.5 text-xs mt-2">
          <label className="text-[10px] font-bold text-slate-500 uppercase">Target Career Domain</label>
          <select className="bg-slate-900 border border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-300">
            <option>Platform & Distributed Systems Engineering</option>
            <option>Machine Learning & Data Engineering</option>
            <option>Frontend & Client Application Engineering</option>
          </select>
        </div>

        <button className="py-2 rounded bg-violet-600 hover:bg-violet-500 text-white font-bold text-xs mt-4 transition">
          Apply Configuration
        </button>
      </div>
    </div>
  );
}
