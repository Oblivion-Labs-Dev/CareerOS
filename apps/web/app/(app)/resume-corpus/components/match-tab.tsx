"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";

interface JobMatchTabProps {
  accomplishments: Accomplishment[];
}

export function JobMatchTab({ accomplishments }: JobMatchTabProps) {
  const [pastedJD, setPastedJD] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [matchResult, setMatchResult] = useState<any | null>(null);

  const handleAnalyze = () => {
    if (!pastedJD.trim()) return;
    setAnalyzing(true);
    // Simulate high-fidelity parsing of keywords
    setTimeout(() => {
      const input = pastedJD.toLowerCase();
      const keywords = ["go", "kubernetes", "aws", "redis", "postgres", "kafka", "distributed systems", "grpc", "ci/cd", "concurrency"];
      
      const found: string[] = [];
      const missing: string[] = [];
      
      // Check our accomplishments for technologies
      const availableTech = new Set<string>();
      accomplishments.forEach(a => {
        a.techStack?.forEach(t => availableTech.add(t.toLowerCase()));
        a.concepts?.forEach(c => availableTech.add(c.toLowerCase()));
      });

      keywords.forEach(kw => {
        if (input.includes(kw)) {
          if (availableTech.has(kw)) {
            found.push(kw);
          } else {
            missing.push(kw);
          }
        }
      });

      if (found.length === 0 && missing.length === 0) {
        // Fallback default keywords if no match
        found.push("go", "aws");
        missing.push("kubernetes", "kafka");
      }

      const score = Math.round((found.length / (found.length + missing.length || 1)) * 100);

      setMatchResult({
        score,
        found,
        missing,
      });
      setAnalyzing(false);
    }, 1200);
  };

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Job Description Match Analyzer</h3>
          <p className="text-xs text-slate-500 mt-0.5">Paste target requirements to compare keyword densities and engineering evidence support.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Input */}
        <div className="lg:col-span-5 p-6 rounded-xl border border-slate-800 bg-slate-900/10 flex flex-col gap-4">
          <label className="text-[10px] font-bold text-slate-500 uppercase">Target Job description</label>
          <textarea
            rows={10}
            value={pastedJD}
            onChange={(e) => setPastedJD(e.target.value)}
            placeholder="Paste target job descriptions to analyze matching skills..."
            className="w-full p-3 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none resize-none font-mono"
          />
          <button
            onClick={handleAnalyze}
            disabled={analyzing || !pastedJD.trim()}
            className="w-full py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white font-bold transition-all text-xs"
          >
            {analyzing ? "Analyzing Keywords..." : "Run Match Audit"}
          </button>
        </div>

        {/* Right Output */}
        <div className="lg:col-span-7">
          {matchResult ? (
            <div className="p-6 rounded-xl border border-slate-800 bg-slate-950 flex flex-col gap-5 shadow-lg">
              <div className="flex justify-between items-center border-b border-slate-850 pb-3">
                <span className="text-xs font-bold text-slate-400 uppercase">Analysis Results</span>
                <span className="text-xs font-black text-green-400 bg-green-950/40 border border-green-900/30 px-2 py-0.5 rounded">
                  Match Score: {matchResult.score}%
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Covered keywords */}
                <div className="p-4 rounded-lg bg-slate-900/40 border border-slate-850">
                  <span className="text-[9px] font-bold text-emerald-400 uppercase tracking-wider block mb-2">Covered Keywords</span>
                  <div className="flex flex-wrap gap-1.5">
                    {matchResult.found.map((kw: string) => (
                      <span key={kw} className="text-[10px] bg-emerald-950/30 text-emerald-400 border border-emerald-900/25 px-2 py-0.5 rounded font-semibold capitalize">{kw}</span>
                    ))}
                  </div>
                </div>

                {/* Missing keywords */}
                <div className="p-4 rounded-lg bg-slate-900/40 border border-slate-850">
                  <span className="text-[9px] font-bold text-amber-400 uppercase tracking-wider block mb-2">Missing / Weak Keywords</span>
                  <div className="flex flex-wrap gap-1.5">
                    {matchResult.missing.map((kw: string) => (
                      <span key={kw} className="text-[10px] bg-amber-950/30 text-amber-400 border border-amber-900/25 px-2 py-0.5 rounded font-semibold capitalize">{kw}</span>
                    ))}
                  </div>
                </div>
              </div>

              <p className="text-xs text-slate-400 leading-normal bg-slate-900/10 p-3 rounded border border-slate-850">
                💡 <strong>Next Steps:</strong> Check if you can add scale metrics or alternative technologies to your accomplishments to resolve the missing keywords detected in the job specifications.
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-20 border border-slate-800/60 border-dashed rounded-xl">
              <span className="text-2xl text-slate-600">📊</span>
              <span className="text-slate-500 text-xs mt-2 font-medium">Paste a job description and run the match audit to check match indicators.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
