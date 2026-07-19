"use client";

import React from "react";

export function TemplatesTab() {
  const templates = [
    { name: "Principal Architecture Standard", desc: "Optimized for system design reviews and multi-tenant scaling systems.", layout: "Traditional Single Column" },
    { name: "ATS Scannable Matrix", desc: "Maximized density of technical terms and metric achievements.", layout: "Modern Two Column" },
    { name: "Executive Business Value", desc: "Focuses on cost reductions, engineering velocity, and leadership alignments.", layout: "Spacious Single Column" },
  ];

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Resume Templates Catalog</h3>
          <p className="text-xs text-slate-500 mt-0.5">Select a presentation schema that matches your current seniority goals.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {templates.map((tpl) => (
          <div
            key={tpl.name}
            className="p-5 rounded-xl border border-slate-800 bg-slate-900/10 hover:bg-slate-900/30 transition flex flex-col justify-between min-h-[140px]"
          >
            <div>
              <span className="text-xs font-bold text-white">{tpl.name}</span>
              <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">{tpl.desc}</p>
            </div>
            <span className="text-[9px] font-bold text-violet-400 uppercase tracking-widest mt-4">Layout: {tpl.layout}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
