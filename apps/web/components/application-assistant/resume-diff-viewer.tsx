"use client";

import React, { useState } from "react";
import { BulletDiffItem } from "@/lib/application-assistant-api";

interface ResumeDiffViewerProps {
  bullets: BulletDiffItem[];
}

export function ResumeDiffViewer({ bullets }: ResumeDiffViewerProps) {
  const [viewMode, setViewMode] = useState<"side-by-side" | "inline">("inline");

  return (
    <div className="space-y-4 font-sans text-sm">
      <div className="flex items-center justify-between border-b border-white/10 pb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
            Résumé Bullet Tailoring
          </span>
          <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            {bullets.filter((b) => b.isModified).length} Tailored Adjustments
          </span>
        </div>
        <div className="flex items-center gap-1 bg-white/5 p-1 rounded-xl border border-white/10">
          <button
            onClick={() => setViewMode("inline")}
            className={`px-3 py-1 text-xs font-medium rounded-lg transition-all cursor-pointer ${
              viewMode === "inline"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Inline Diff
          </button>
          <button
            onClick={() => setViewMode("side-by-side")}
            className={`px-3 py-1 text-xs font-medium rounded-lg transition-all cursor-pointer ${
              viewMode === "side-by-side"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            Side-by-Side
          </button>
        </div>
      </div>

      <div className="space-y-3">
        {bullets.map((bullet) => (
          <div
            key={bullet.index}
            className={`p-4 rounded-xl border transition-all ${
              bullet.isModified
                ? "bg-[#0b1622]/80 border-cyan-500/30 shadow-[0_4px_16px_rgba(0,180,216,0.08)]"
                : "bg-slate-900/40 border-white/5"
            }`}
          >
            {viewMode === "inline" ? (
              <div className="leading-relaxed">
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-white/5">
                    Bullet #{bullet.index + 1}
                  </span>
                  {bullet.isModified ? (
                    <span className="text-[10px] font-bold text-cyan-400">⚡ Keyword Aligned</span>
                  ) : (
                    <span className="text-[10px] text-slate-500">Unchanged</span>
                  )}
                </div>
                <p className="text-slate-200">
                  {bullet.chunks.map((chunk, cIdx) => {
                    if (chunk.type === "add") {
                      return (
                        <span
                          key={cIdx}
                          className="bg-emerald-500/20 text-emerald-300 px-1 py-0.5 rounded border border-emerald-500/40 font-medium mx-0.5"
                        >
                          +{chunk.text}
                        </span>
                      );
                    }
                    if (chunk.type === "del") {
                      return (
                        <span
                          key={cIdx}
                          className="bg-rose-500/20 text-rose-300 line-through px-1 py-0.5 rounded border border-rose-500/30 text-xs opacity-75 mx-0.5"
                        >
                          -{chunk.text}
                        </span>
                      );
                    }
                    return <span key={cIdx}>{chunk.text} </span>;
                  })}
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="p-3 rounded-lg bg-rose-950/20 border border-rose-500/20">
                  <span className="text-[10px] font-bold uppercase text-rose-400 block mb-1">
                    Original Master Bullet
                  </span>
                  <p className="text-xs text-slate-300 leading-relaxed">{bullet.original || "(None)"}</p>
                </div>
                <div className="p-3 rounded-lg bg-emerald-950/20 border border-emerald-500/30">
                  <span className="text-[10px] font-bold uppercase text-emerald-400 block mb-1">
                    Tailored Job Bullet
                  </span>
                  <p className="text-xs text-emerald-100 font-medium leading-relaxed">
                    {bullet.tailored || "(None)"}
                  </p>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
