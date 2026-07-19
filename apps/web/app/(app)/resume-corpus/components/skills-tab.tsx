"use client";

import React, { useState } from "react";
import { Accomplishment } from "../types";

interface SkillsTabProps {
  accomplishments: Accomplishment[];
}

export function SkillsTab({ accomplishments }: SkillsTabProps) {
  const [hoveredSkill, setHoveredSkill] = useState<string | null>(null);

  // Compile map of skills
  const skillsMap = new Map<string, { name: string; count: number; accomplishments: string[]; depth: string }>();

  accomplishments.forEach((acc) => {
    acc.techStack?.forEach((tech) => {
      const key = tech.toLowerCase();
      const existing = skillsMap.get(key) || { name: tech, count: 0, accomplishments: [], depth: "Working Knowledge" };
      
      // Determine depth based on frequency of use or scale
      let depth = "Working Knowledge";
      if (acc.roastResistanceScore > 85) depth = "Deep Expertise";
      else if (acc.completenessStatus === "Complete") depth = "Production Experience";

      existing.count += 1;
      if (!existing.accomplishments.includes(acc.project)) {
        existing.accomplishments.push(acc.project);
      }
      existing.depth = depth;
      skillsMap.set(key, existing);
    });
  });

  const allSkills = Array.from(skillsMap.values());

  return (
    <div className="flex flex-col gap-6 animate-fade-in text-slate-100">
      <div className="flex justify-between items-center border-b border-slate-800 pb-3">
        <div>
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">Skills Competency Matrix</h3>
          <p className="text-xs text-slate-500 mt-0.5">Explore your technical stack mapped directly to verified project achievements.</p>
        </div>
      </div>

      {allSkills.length === 0 ? (
        <div className="text-xs text-slate-500 italic py-12 text-center border border-slate-800 border-dashed rounded-lg">
          No skills parsed. Try adding more achievements to build your skills catalog.
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {allSkills.map((skill) => {
            const isHovered = hoveredSkill === skill.name;
            return (
              <div
                key={skill.name}
                onMouseEnter={() => setHoveredSkill(skill.name)}
                onMouseLeave={() => setHoveredSkill(null)}
                className="p-4 rounded-xl border border-slate-800 bg-slate-900/10 hover:bg-slate-900/30 hover:border-slate-700/80 transition relative flex flex-col justify-between min-h-[100px] cursor-help group"
              >
                <div>
                  <span className="text-xs font-bold text-white group-hover:text-violet-400 transition">{skill.name}</span>
                  <span className="text-[10px] text-slate-500 block mt-1 font-semibold">{skill.count} Projects linked</span>
                </div>
                
                <span className={`text-[9px] font-bold uppercase px-2 py-0.5 rounded tracking-wide self-start mt-3 ${
                  skill.depth === "Deep Expertise"
                    ? "bg-violet-950/40 text-violet-400 border border-violet-900/30"
                    : skill.depth === "Production Experience"
                      ? "bg-emerald-950/40 text-emerald-400 border border-emerald-900/25"
                      : "bg-slate-900 text-slate-400 border border-slate-850"
                }`}>
                  {skill.depth}
                </span>

                {/* Hover Details Panel */}
                {isHovered && (
                  <div className="absolute top-full left-0 right-0 z-20 mt-1.5 p-3 rounded-lg bg-slate-950 border border-slate-850 shadow-2xl text-[10px] flex flex-col gap-1.5 animate-fade-in text-slate-300">
                    <span className="font-bold text-white block">Project History:</span>
                    <ul className="list-disc list-inside flex flex-col gap-0.5 text-slate-400">
                      {skill.accomplishments.map((p, idx) => (
                        <li key={idx} className="truncate">{p}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
