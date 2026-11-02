"use client";

import React from "react";
import { IconBolt } from "./icons";

interface OrbitRadarGraphicProps {
  isRunning: boolean;
  isCompleted?: boolean;
}

export function OrbitRadarGraphic({ isRunning, isCompleted }: OrbitRadarGraphicProps) {
  return (
    <div className="autopilot-orbit relative w-44 h-44 sm:w-48 sm:h-48 flex items-center justify-center select-none">
      {/* Background Radial Glow */}
      <div
        className="absolute inset-0 rounded-full blur-2xl transition-all duration-700 pointer-events-none"
        style={{
          background: isRunning
            ? "radial-gradient(circle, var(--accent-glow), transparent 70%)"
            : isCompleted
              ? "radial-gradient(circle, var(--accent-soft), transparent 70%)"
              : "radial-gradient(circle, var(--border), transparent 70%)",
          transform: isRunning ? "scale(1.1)" : isCompleted ? "scale(1)" : "scale(0.9)",
        }}
      />

      {/* SVG Concentric Orbital Rings */}
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 200 200">
        {/* Outer Ring 1 */}
        <circle
          cx="100"
          cy="100"
          r="88"
          fill="none"
          stroke="var(--accent-tertiary)"
          strokeOpacity="0.34"
          strokeWidth="1"
          strokeDasharray="4 6"
        />

        {/* Outer Ring 2 */}
        <circle
          cx="100"
          cy="100"
          r="72"
          fill="none"
          stroke="var(--accent)"
          strokeOpacity={isRunning || isCompleted ? 0.5 : 0.25}
          strokeWidth="1.2"
        />

        {/* Mid Ring 3 */}
        <circle
          cx="100"
          cy="100"
          r="54"
          fill="none"
          stroke="var(--accent)"
          strokeOpacity="0.3"
          strokeWidth="1"
          strokeDasharray="2 4"
        />

        {/* Inner Ring 4 */}
        <circle
          cx="100"
          cy="100"
          r="38"
          fill="none"
          stroke={isRunning || isCompleted ? "var(--accent)" : "var(--muted)"}
          strokeOpacity={isRunning || isCompleted ? 0.55 : 0.25}
          strokeWidth="1"
        />

        {/* Dynamic Sweeping Radar Beam (While Running) */}
        {isRunning && (
          <g className="animate-[spin_4s_linear_infinite] origin-center">
            <defs>
              <linearGradient id="radarBeamGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.45" />
                <stop offset="60%" stopColor="var(--accent-tertiary)" stopOpacity="0.1" />
                <stop offset="100%" stopColor="transparent" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M 100 100 L 100 12 A 88 88 0 0 1 176 144 Z" fill="url(#radarBeamGrad)" opacity="0.8" />
            <line x1="100" y1="100" x2="176" y2="144" stroke="var(--accent)" strokeWidth="1.5" strokeOpacity="0.8" />
          </g>
        )}

        {/* Orbiting Satellite Particle 1 */}
        {isRunning ? (
          <g className="animate-[spin_6s_linear_infinite] origin-center">
            <circle cx="100" cy="28" r="3.5" fill="var(--accent)" />
            <circle cx="100" cy="28" r="7" fill="var(--accent)" opacity="0.3" className="animate-ping" />
          </g>
        ) : (
          <circle cx="100" cy="28" r="3" fill="var(--accent-tertiary)" opacity="0.9" />
        )}

        {/* Orbiting Satellite Particle 2 */}
        {isRunning ? (
          <g className="animate-[spin_9s_linear_infinite_reverse] origin-center">
            <circle cx="154" cy="100" r="2.5" fill="var(--accent)" />
          </g>
        ) : (
          <circle cx="154" cy="100" r="2.5" fill="var(--accent)" opacity="0.6" />
        )}
      </svg>

      {/* Central Core Sphere */}
      <div
        className="relative z-10 w-16 h-16 sm:w-20 sm:h-20 rounded-full flex items-center justify-center border transition-all duration-500 backdrop-blur-xl"
        style={{
          background: "var(--card)",
          borderColor: isRunning || isCompleted ? "var(--accent)" : "var(--border-strong)",
          borderWidth: isRunning || isCompleted ? 1.5 : 1,
          boxShadow: isRunning
            ? "0 0 30px var(--accent-glow)"
            : isCompleted
              ? "0 0 20px var(--accent-soft)"
              : "var(--shadow-sm)",
          transform: isRunning ? "scale(1.05)" : "scale(1)",
        }}
      >
        {/* Core Center Icon */}
        <div className="relative flex items-center justify-center">
          <div
            className="w-8 h-8 rounded-full flex items-center justify-center transition-colors"
            style={{ color: isRunning || isCompleted ? "var(--accent)" : "var(--muted)" }}
          >
            <IconBolt className={`w-5 h-5 sm:w-6 sm:h-6 ${isRunning ? "animate-pulse" : ""}`} />
          </div>

          {/* Central Ping Ring */}
          {isRunning && (
            <span className="absolute inset-0 rounded-full border opacity-40 animate-ping" style={{ borderColor: "var(--accent)" }} />
          )}
        </div>
      </div>
    </div>
  );
}
