"use client";

import React from "react";
import { IconBolt } from "./icons";

interface OrbitRadarGraphicProps {
  isRunning: boolean;
  isCompleted?: boolean;
}

export function OrbitRadarGraphic({ isRunning, isCompleted }: OrbitRadarGraphicProps) {
  return (
    <div className="relative w-44 h-44 sm:w-48 sm:h-48 flex items-center justify-center select-none">
      {/* Background Radial Glow */}
      <div
        className={`absolute inset-0 rounded-full blur-2xl transition-all duration-700 pointer-events-none ${
          isRunning
            ? "bg-gradient-to-tr from-[#2ee8c9]/20 via-[#38bdf8]/15 to-transparent scale-110"
            : isCompleted
            ? "bg-[#2ee8c9]/10 scale-100"
            : "bg-white/[0.02] scale-90"
        }`}
      />

      {/* SVG Concentric Orbital Rings */}
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 200 200">
        {/* Outer Ring 1 */}
        <circle
          cx="100"
          cy="100"
          r="88"
          fill="none"
          stroke="rgba(148, 163, 184, 0.12)"
          strokeWidth="1"
          strokeDasharray="4 6"
        />

        {/* Outer Ring 2 */}
        <circle
          cx="100"
          cy="100"
          r="72"
          fill="none"
          stroke={isRunning ? "rgba(46, 232, 201, 0.25)" : "rgba(148, 163, 184, 0.16)"}
          strokeWidth="1.2"
        />

        {/* Mid Ring 3 */}
        <circle
          cx="100"
          cy="100"
          r="54"
          fill="none"
          stroke="rgba(148, 163, 184, 0.14)"
          strokeWidth="1"
          strokeDasharray="2 4"
        />

        {/* Inner Ring 4 */}
        <circle
          cx="100"
          cy="100"
          r="38"
          fill="none"
          stroke={isRunning ? "rgba(56, 189, 248, 0.4)" : "rgba(148, 163, 184, 0.2)"}
          strokeWidth="1"
        />

        {/* Dynamic Sweeping Radar Beam (While Running) */}
        {isRunning && (
          <g className="animate-[spin_4s_linear_infinite] origin-center">
            <defs>
              <linearGradient id="radarBeamGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#2ee8c9" stopOpacity="0.45" />
                <stop offset="60%" stopColor="#38bdf8" stopOpacity="0.1" />
                <stop offset="100%" stopColor="transparent" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M 100 100 L 100 12 A 88 88 0 0 1 176 144 Z" fill="url(#radarBeamGrad)" opacity="0.8" />
            <line x1="100" y1="100" x2="176" y2="144" stroke="#2ee8c9" strokeWidth="1.5" strokeOpacity="0.8" />
          </g>
        )}

        {/* Orbiting Satellite Particle 1 */}
        {isRunning ? (
          <g className="animate-[spin_6s_linear_infinite] origin-center">
            <circle cx="100" cy="28" r="3.5" fill="#2ee8c9" />
            <circle cx="100" cy="28" r="7" fill="#2ee8c9" opacity="0.3" className="animate-ping" />
          </g>
        ) : (
          <circle cx="100" cy="28" r="3" fill="#64748b" opacity="0.6" />
        )}

        {/* Orbiting Satellite Particle 2 */}
        {isRunning ? (
          <g className="animate-[spin_9s_linear_infinite_reverse] origin-center">
            <circle cx="154" cy="100" r="2.5" fill="#38bdf8" />
          </g>
        ) : (
          <circle cx="154" cy="100" r="2" fill="#475569" opacity="0.5" />
        )}
      </svg>

      {/* Central Core Sphere */}
      <div
        className={`relative z-10 w-16 h-16 sm:w-20 sm:h-20 rounded-full flex items-center justify-center border transition-all duration-500 shadow-2xl backdrop-blur-xl ${
          isRunning
            ? "bg-gradient-to-br from-[#0c1c28] via-[#091520] to-[#060c14] border-[#2ee8c9]/50 shadow-[0_0_30px_rgba(46,232,201,0.35)] scale-105"
            : isCompleted
            ? "bg-[#09141c] border-[#2ee8c9]/40 shadow-[0_0_20px_rgba(46,232,201,0.2)]"
            : "bg-[#0c121c] border-white/10 shadow-[0_0_15px_rgba(0,0,0,0.4)]"
        }`}
      >
        {/* Core Center Icon */}
        <div className="relative flex items-center justify-center">
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center transition-colors ${
              isRunning ? "text-[#2ee8c9]" : isCompleted ? "text-cyan-300" : "text-slate-400"
            }`}
          >
            <IconBolt className={`w-5 h-5 sm:w-6 sm:h-6 ${isRunning ? "animate-pulse" : ""}`} />
          </div>

          {/* Central Ping Ring */}
          {isRunning && (
            <span className="absolute inset-0 rounded-full border border-[#2ee8c9] opacity-40 animate-ping" />
          )}
        </div>
      </div>
    </div>
  );
}
