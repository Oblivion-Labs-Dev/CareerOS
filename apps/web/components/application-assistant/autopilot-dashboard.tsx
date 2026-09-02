"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  getAutopilotEventSource,
  getAutopilotStatus,
  pauseAutopilot,
  startAutopilot,
  stopAutopilot,
} from "@/lib/application-assistant-api";
import {
  IconActivity,
  IconBolt,
  IconCheck,
  IconPause,
  IconPlay,
  IconRefresh,
  IconSettings,
  IconSquare,
} from "./autopilot/icons";
import { OrbitRadarGraphic } from "./autopilot/orbit-radar-graphic";
import { ProgressPipeline } from "./autopilot/progress-pipeline";
import { DonutProgressRing } from "./autopilot/donut-progress-ring";
import { MetricsRibbon } from "./autopilot/metrics-ribbon";
import { SystemHealthPanel } from "./autopilot/system-health-panel";
import { RecentActivityPanel } from "./autopilot/recent-activity-panel";
import { BatchConfigModal } from "./autopilot/batch-config-modal";

interface AutopilotDashboardProps {
  onNavigateTab?: (tab: "autopilot" | "submitted" | "review" | "failed" | "tracker") => void;
}

const BATCH_PRESETS = [1, 5, 10, 15, 30, 50];

function formatElapsedTime(startedAt?: string): string {
  if (!startedAt) return "0m";
  const start = new Date(startedAt).getTime();
  const now = Date.now();
  const diffSec = Math.max(0, Math.floor((now - start) / 1000));
  const hrs = Math.floor(diffSec / 3600);
  const mins = Math.floor((diffSec % 3600) / 60);
  if (hrs > 0) return `${hrs}h ${mins}m`;
  return `${mins}m`;
}

function formatEstRemaining(processed: number, target: number, startedAt?: string): string {
  if (processed >= target || !startedAt || processed === 0) return "—";
  const start = new Date(startedAt).getTime();
  const now = Date.now();
  const elapsedSec = Math.max(1, (now - start) / 1000);
  const avgPerJob = elapsedSec / processed;
  const remJobs = target - processed;
  const remSec = Math.round(avgPerJob * remJobs);
  const hrs = Math.floor(remSec / 3600);
  const mins = Math.floor((remSec % 3600) / 60);
  if (hrs > 0) return `${hrs}h ${mins}m`;
  return `${mins}m`;
}

export function AutopilotDashboard({ onNavigateTab }: AutopilotDashboardProps) {
  const [statusData, setStatusData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedBatchSize, setSelectedBatchSize] = useState<number>(1);
  const [customBatchInput, setCustomBatchInput] = useState<string>("");
  const [isCustomMode, setIsCustomMode] = useState<boolean>(false);
  const [showConfigModal, setShowConfigModal] = useState<boolean>(false);
  const [selectedModel, setSelectedModel] = useState<string>("mistral-small3.2:24b");
  const statusRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchStatus = async () => {
    try {
      const res = await getAutopilotStatus();
      setStatusData(res);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Could not connect to Autopilot service");
    }
  };

  useEffect(() => {
    fetchStatus();

    // ── Realtime Push Model via Server-Sent Events (SSE) ──
    let es: EventSource | null = null;
    try {
      es = getAutopilotEventSource();

      es.addEventListener("status", (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          setStatusData(data);
          setError(null);
        } catch {}
      });

      es.addEventListener("log", (e: MessageEvent) => {
        try {
          const logEntry = JSON.parse(e.data);
          setStatusData((prev: any) => {
            if (!prev) return prev;
            const updatedLogs = [logEntry, ...(prev.recentLogs || [])].slice(0, 100);
            return { ...prev, recentLogs: updatedLogs };
          });
          // A busy run can emit many granular events in one second. Coalesce
          // status refreshes instead of issuing one database request per event.
          if (!statusRefreshTimer.current) {
            statusRefreshTimer.current = setTimeout(() => {
              statusRefreshTimer.current = null;
              fetchStatus();
            }, 750);
          }
        } catch {}
      });

      es.onerror = () => {
        // Fallback gracefully to polling if SSE drops
      };
    } catch (e) {
      console.warn("SSE connection error, falling back to interval:", e);
    }

    // SSE provides immediate activity updates; this is only a recovery sync.
    const interval = setInterval(fetchStatus, 10000);
    return () => {
      if (es) {
        es.close();
      }
      if (statusRefreshTimer.current) {
        clearTimeout(statusRefreshTimer.current);
      }
      clearInterval(interval);
    };
  }, []);

  const handleStart = async (customCount?: number, opts?: { concurrency?: number; staggerDelay?: number; selfHealing?: boolean }) => {
    setLoading(true);
    setError(null);
    const targetCount = customCount || (isCustomMode ? parseInt(customBatchInput) || 5 : selectedBatchSize);
    try {
      await startAutopilot({
        targetProcessCount: targetCount,
        concurrency: opts?.concurrency ?? 5,
        staggerDelay: opts?.staggerDelay ?? 0.5,
        selfHealing: opts?.selfHealing ?? true,
      });
      await fetchStatus();
      setShowConfigModal(false);
    } catch (err: any) {
      setError(err?.message || "Failed to start Autopilot run");
    } finally {
      setLoading(false);
    }
  };

  const handlePause = async () => {
    setLoading(true);
    try {
      await pauseAutopilot();
      await fetchStatus();
    } catch (err: any) {
      setError(err?.message || "Failed to pause Autopilot");
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await stopAutopilot();
      await fetchStatus();
    } catch (err: any) {
      setError(err?.message || "Failed to stop Autopilot");
    } finally {
      setLoading(false);
    }
  };

  const isRunning =
    statusData?.running ||
    statusData?.status === "RUNNING" ||
    statusData?.status === "RECOVERING";
  const isPaused = statusData?.status === "PAUSED";
  const isCompleted = statusData?.status === "COMPLETED";
  const run = statusData?.run || {};
  const activeJob = statusData?.activeJob;
  const recentLogs = statusData?.recentLogs || [];

  const targetCount = run.targetProcessCount || selectedBatchSize;
  const processedCount = run.processedCount || 0;
  const submittedCount = run.submittedCount || 0;
  const stagedCount = run.stagedCount || 0;
  const skippedCount = run.skippedCount || 0;
  const failedCount = run.failedCount || 0;
  const queueSize = statusData?.queueSize || 0;

  // Cumulative totals across all applications
  const cumulative = statusData?.cumulative || {};
  const totalSubmitted = cumulative.submitted ?? submittedCount;
  const totalStaged = cumulative.staged ?? stagedCount;
  const totalSkipped = cumulative.skipped ?? skippedCount;
  const totalFailed = cumulative.failed ?? failedCount;
  const totalProcessed = cumulative.processed ?? (totalSubmitted + totalStaged + totalSkipped + totalFailed);

  const progressPercent = Math.min(
    100,
    Math.round((processedCount / (targetCount || 1)) * 100)
  );

  const startTimeStr = run.startedAt
    ? new Date(run.startedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "10:42 PM";
  const elapsedTimeStr = formatElapsedTime(run.startedAt);
  const estRemainingStr = formatEstRemaining(processedCount, targetCount, run.startedAt);

  return (
    <div className="space-y-6 font-sans text-slate-100 pb-12">
      {/* Error Notice */}
      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center justify-between gap-3 shadow-lg backdrop-blur-md">
          <div className="flex items-center gap-2">
            <span>⚠️</span>
            <span>{error}</span>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-rose-400 hover:text-rose-200 font-bold px-2 py-0.5 cursor-pointer"
          >
            ✕
          </button>
        </div>
      )}

      {/* ─── 1. Main Run Progress & Current Status (2-Column Grid Matching Mockup 1) ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Left: Primary Run Progress Card (~68% width on desktop) */}
        <div className="lg:col-span-8 relative overflow-hidden rounded-2xl border border-white/10 bg-[radial-gradient(circle_at_78%_18%,rgba(56,189,248,0.10),transparent_26%),radial-gradient(circle_at_18%_84%,rgba(99,102,241,0.08),transparent_28%),linear-gradient(to_bottom,#0e1622,#0a1019,#070b12)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.28)] backdrop-blur-2xl flex flex-col justify-between space-y-6">
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/70 to-violet-300/40" />
          {/* Top Label & Status Pill & Actions */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="text-[11px] font-black tracking-wider text-slate-400 uppercase">
                RUN PROGRESS
              </span>
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-500/15 border border-indigo-500/30 text-[11px] font-mono text-indigo-300">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                <span>Model: <strong>mistral-small3.2:24b</strong></span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={async () => {
                  if (confirm("Reset entire autopilot queue, active runs, and drafts back to clean initial state?")) {
                    setLoading(true);
                    try {
                      const { resetAutopilotQueue } = await import("@/lib/application-assistant-api");
                      const res = await resetAutopilotQueue();
                      alert(`Queue reset successfully: ${res.resetJobsCount} jobs ready.`);
                      await fetchStatus();
                    } catch (err: any) {
                      setError(err?.message || "Failed to reset queue");
                    } finally {
                      setLoading(false);
                    }
                  }
                }}
                disabled={loading || isRunning}
                className="px-3 py-1 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-slate-300 hover:text-white text-xs font-bold flex items-center gap-1.5 transition-all cursor-pointer disabled:opacity-40"
                title="Reset queue and all jobs"
              >
                <IconRefresh className="w-3.5 h-3.5" />
                <span>Reset Queue</span>
              </button>

              <span
                style={{
                  background: isCompleted ? "rgba(6, 182, 212, 0.15)" : isRunning ? "rgba(46, 232, 201, 0.15)" : "rgba(255, 255, 255, 0.05)",
                  borderColor: isCompleted ? "rgba(6, 182, 212, 0.4)" : isRunning ? "rgba(46, 232, 201, 0.4)" : "rgba(255, 255, 255, 0.1)",
                  color: isCompleted ? "#67e8f9" : isRunning ? "#2ee8c9" : "#94a3b8",
                  boxShadow: isRunning ? "0 0 15px rgba(46, 232, 201, 0.3)" : "none",
                }}
                className="px-3.5 py-1 rounded-full text-xs font-black tracking-wider uppercase border transition-all flex items-center gap-1.5"
              >
                <span>✓</span> {isCompleted ? "RUN COMPLETED" : isRunning ? "RUNNING" : "READY"}
              </span>
            </div>
          </div>

          {/* Center Graphic & Batch Controls */}
          <div className="flex flex-col sm:flex-row items-center gap-6 sm:gap-8">
            {/* Orbit Radar Graphic */}
            <div className="shrink-0">
              <OrbitRadarGraphic isRunning={isRunning} isCompleted={isCompleted} />
            </div>

            {/* Progress & Batch Preset Details */}
            <div className="flex-1 w-full space-y-4">
              <p className="text-xs text-slate-300 leading-relaxed">
                Autonomous job application runner with 100% crash isolation, pre-submit safety checks, and grounded candidate profile matching.
              </p>

              {/* Batch Size Selector Buttons (Matching Mockup 1) */}
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <span className="text-xs font-black text-slate-300 mr-1">Batch Size:</span>
                <div className="flex items-center gap-1.5 bg-black/20 p-1.5 rounded-xl border border-white/[0.12] shadow-inner backdrop-blur-sm">
                  {BATCH_PRESETS.map((size) => (
                    <button
                      key={size}
                      onClick={() => {
                        setSelectedBatchSize(size);
                        setIsCustomMode(false);
                      }}
                      style={{
                        background: !isCustomMode && selectedBatchSize === size ? "rgba(46, 232, 201, 0.2)" : "#09101b",
                        borderColor: !isCustomMode && selectedBatchSize === size ? "#2ee8c9" : "rgba(255, 255, 255, 0.1)",
                        color: !isCustomMode && selectedBatchSize === size ? "#2ee8c9" : "#94a3b8",
                        boxShadow: !isCustomMode && selectedBatchSize === size ? "0 0 14px rgba(46, 232, 201, 0.35)" : "none",
                      }}
                      className="px-3.5 py-1.5 rounded-lg text-xs font-black border transition-all cursor-pointer hover:text-white"
                    >
                      {size}
                    </button>
                  ))}
                  <button
                    onClick={() => setIsCustomMode(true)}
                    style={{
                      background: isCustomMode ? "rgba(46, 232, 201, 0.2)" : "#09101b",
                      borderColor: isCustomMode ? "#2ee8c9" : "rgba(255, 255, 255, 0.1)",
                      color: isCustomMode ? "#2ee8c9" : "#94a3b8",
                      boxShadow: isCustomMode ? "0 0 14px rgba(46, 232, 201, 0.35)" : "none",
                    }}
                    className="px-3.5 py-1.5 rounded-lg text-xs font-black border transition-all cursor-pointer hover:text-white"
                  >
                    Custom
                  </button>
                </div>

                {isCustomMode && (
                  <input
                    type="number"
                    min="1"
                    max="500"
                    placeholder="Count..."
                    value={customBatchInput}
                    onChange={(e) => setCustomBatchInput(e.target.value)}
                    className="w-20 px-2.5 py-1.5 rounded-xl bg-[#06090e] border border-white/15 text-slate-100 text-xs focus:outline-none focus:border-[#2ee8c9]"
                  />
                )}
              </div>

              {/* Live Batch Progress Bar (While Running/Complete) */}
              <div className="space-y-1.5 pt-1">
                <div className="flex justify-between text-xs text-slate-300 font-mono">
                  <span>Batch Progress: <strong className="text-[#2ee8c9] font-black">{processedCount} / {targetCount} processed</strong></span>
                  <span className="font-bold">{progressPercent}%</span>
                </div>
                <div className="w-full bg-black/35 rounded-full h-2.5 overflow-hidden border border-white/[0.08]">
                  <div
                    className="bg-gradient-to-r from-[#2ee8c9] via-[#38bdf8] to-[#818cf8] h-full rounded-full transition-all duration-700 shadow-[0_0_12px_rgba(46,232,201,0.5)]"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              </div>

              {/* Stepper Pipeline */}
              <ProgressPipeline
                currentStep={activeJob?.currentStep}
                isRunning={isRunning}
                isCompleted={isCompleted}
              />
            </div>
          </div>

          {/* Bottom Metadata Block */}
          <div className="pt-4 border-t border-white/5 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="p-2.5 rounded-xl bg-white/[0.035] border border-white/[0.07] space-y-0.5 backdrop-blur-sm">
              <span className="text-[10px] uppercase font-bold text-slate-500 block">Started</span>
              <span className="font-mono text-slate-200 font-semibold">{startTimeStr}</span>
            </div>

            <div className="p-2.5 rounded-xl bg-white/[0.035] border border-white/[0.07] space-y-0.5 backdrop-blur-sm">
              <span className="text-[10px] uppercase font-bold text-slate-500 block">Elapsed</span>
              <span className="font-mono text-slate-200 font-semibold">{elapsedTimeStr}</span>
            </div>

            <div className="p-2.5 rounded-xl bg-white/[0.035] border border-white/[0.07] space-y-0.5 backdrop-blur-sm">
              <span className="text-[10px] uppercase font-bold text-slate-500 block">Est. Remaining</span>
              <span className="font-mono text-slate-200 font-semibold">{estRemainingStr}</span>
            </div>

            <div className="p-2.5 rounded-xl bg-white/[0.035] border border-white/[0.07] space-y-0.5 backdrop-blur-sm">
              <span className="text-[10px] uppercase font-bold text-slate-500 block">Queue Mode</span>
              <span className="text-[#2ee8c9] font-semibold truncate block">Highest Match First</span>
            </div>
          </div>
        </div>

        {/* Right: Current Status Card (~32% width on desktop) */}
        <div className="lg:col-span-4 relative overflow-hidden rounded-2xl border border-white/10 bg-[radial-gradient(circle_at_72%_8%,rgba(45,212,191,0.11),transparent_30%),radial-gradient(circle_at_24%_92%,rgba(139,92,246,0.08),transparent_32%),linear-gradient(to_bottom,#0e1622,#0a1019,#070b12)] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.28)] backdrop-blur-2xl flex flex-col justify-between space-y-5">
          <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-emerald-300/60 to-cyan-300/40" />
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <IconActivity className="w-4 h-4 text-[#2ee8c9]" />
              <span className="text-[11px] font-black tracking-wider text-slate-200 uppercase">
                Current Status
              </span>
            </div>
            <span className="text-xs font-bold text-slate-300 font-mono">
              {isRunning ? `${processedCount} / ${targetCount}` : `${totalProcessed} Total`}
            </span>
          </div>

          {/* Donut Progress Ring */}
          <DonutProgressRing
            processed={isRunning ? processedCount : totalProcessed}
            target={targetCount}
            submitted={isRunning ? submittedCount : totalSubmitted}
            staged={isRunning ? stagedCount : totalStaged}
            skipped={isRunning ? skippedCount : totalSkipped}
            failed={isRunning ? failedCount : totalFailed}
            isCompleted={isCompleted}
            onSelectSegment={(seg) => {
              if (seg === "submitted") onNavigateTab?.("submitted");
              else if (seg === "staged") onNavigateTab?.("review");
              else if (seg === "failed") onNavigateTab?.("failed");
              else if (seg === "skipped") onNavigateTab?.("tracker");
            }}
          />

          {/* Run Parameter Badges */}
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-white/5 text-center text-xs">
            <div className="p-2.5 rounded-xl bg-white/[0.035] border border-white/[0.07] backdrop-blur-sm">
              <span className="text-[10px] text-slate-400 uppercase font-bold block">Match Threshold</span>
              <span className="font-extrabold text-[#2ee8c9] text-sm">75+</span>
            </div>

            <div className="p-2.5 rounded-xl bg-white/[0.035] border border-white/[0.07] backdrop-blur-sm">
              <span className="text-[10px] text-slate-400 uppercase font-bold block">Max Post Age</span>
              <span className="font-extrabold text-slate-200 text-sm">7 days</span>
            </div>
          </div>

          {/* Bottom Actions inside Current Status Card (Matching Mockup 1) */}
          <div className="grid grid-cols-2 gap-3 pt-2">
            {!isRunning ? (
              <button
                onClick={() => handleStart()}
                disabled={loading}
                style={{
                  background: "linear-gradient(135deg, rgba(46, 232, 201, 0.15), rgba(56, 189, 248, 0.2))",
                  borderColor: "#2ee8c9",
                  color: "#2ee8c9",
                  boxShadow: "0 0 20px rgba(46, 232, 201, 0.35)",
                }}
                className="w-full py-2.5 rounded-xl border font-black text-xs flex items-center justify-center gap-2 cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
              >
                <IconPlay className="w-3.5 h-3.5 fill-current" />
                Start Run
              </button>
            ) : (
              <button
                onClick={handlePause}
                disabled={loading}
                style={{
                  background: "#0c2925",
                  borderColor: "#2ee8c9",
                  color: "#2ee8c9",
                  boxShadow: "0 0 18px rgba(46, 232, 201, 0.35)",
                }}
                className="w-full py-2.5 rounded-xl border font-black text-xs flex items-center justify-center gap-2 cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
              >
                <IconPause className="w-3.5 h-3.5" />
                Pause
              </button>
            )}

            <button
              onClick={handleStop}
              disabled={loading || (!isRunning && !isPaused)}
              style={{
                background: "#261014",
                borderColor: "rgba(239, 68, 68, 0.5)",
                color: "#f87171",
                boxShadow: (!isRunning && !isPaused) ? "none" : "0 0 12px rgba(239, 68, 68, 0.25)",
              }}
              className="w-full py-2.5 rounded-xl border font-black text-xs flex items-center justify-center gap-2 cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98] disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <IconSquare className="w-3.5 h-3.5 fill-current" />
              Stop
            </button>
          </div>

          {/* Reset Processed Jobs Button */}
          <button
            onClick={async () => {
              if (confirm("Reset all submitted and processed jobs back to UNAPPLIED so they can be re-applied?")) {
                setLoading(true);
                try {
                  const { resetSubmittedAutopilotJobs } = await import("@/lib/application-assistant-api");
                  await resetSubmittedAutopilotJobs("ALL");
                  await fetchStatus();
                } catch (err: any) {
                  setError(err?.message || "Failed to reset jobs");
                } finally {
                  setLoading(false);
                }
              }
            }}
            disabled={loading || isRunning}
            className="w-full py-1.5 rounded-xl border border-amber-500/20 bg-amber-500/5 hover:bg-amber-500/15 text-amber-300 font-semibold text-[11px] flex items-center justify-center gap-1.5 cursor-pointer transition-all disabled:opacity-40"
            title="Reset processed jobs back to unapplied"
          >
            <span>↺</span>
            <span>Reset Processed Jobs to Unapplied</span>
          </button>
        </div>
      </div>

      {/* ─── 2. Metrics Ribbon (5 Cards Row) ─── */}
      <MetricsRibbon
        submitted={totalSubmitted}
        staged={totalStaged}
        skipped={totalSkipped}
        failed={totalFailed}
        queueRemaining={queueSize}
        processedCount={totalProcessed}
        concurrencyMetrics={statusData?.concurrencyMetrics}
        selfHealing={statusData?.selfHealing}
        onSelectCategory={(cat) => {
          if (cat === "SUBMITTED") {
            onNavigateTab?.("submitted");
          } else if (cat === "STAGED") {
            onNavigateTab?.("review");
          } else if (cat === "FAILED") {
            onNavigateTab?.("failed");
          } else if (cat === "QUEUED" || cat === "SKIPPED") {
            onNavigateTab?.("tracker");
          }
        }}
      />

      {/* ─── 4. Grid: Active Job / Timeline + System Health Panel ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Left: Active Job & Activity Timeline (8 cols) */}
        <div className="lg:col-span-8 space-y-5">
          {/* Currently Processing Job Cards */}
          {statusData?.workers && statusData.workers.some((w: any) => w.status !== "idle" && w.status !== "done" && w.currentJob) ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between px-1">
                <span className="text-[11px] font-black text-[#2ee8c9] uppercase tracking-widest flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#2ee8c9] animate-ping" />
                  Active Worker Applications ({statusData.workers.filter((w: any) => w.status !== "idle" && w.status !== "done" && w.currentJob).length})
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {statusData.workers
                  .filter((w: any) => w.status !== "idle" && w.status !== "done" && w.currentJob)
                  .map((w: any) => (
                    <div
                      key={w.workerId}
                      className="p-4 rounded-2xl border border-[#2ee8c9]/40 bg-gradient-to-r from-[#0a1622] via-[#0d1c2a] to-[#08121d] text-slate-200 shadow-xl space-y-2.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 text-[10px] font-mono font-bold flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#2ee8c9] animate-pulse" />
                          W{w.slot + 1} • Worker {w.slot + 1}
                        </span>
                        <span className="px-2.5 py-0.5 rounded-full bg-[#2ee8c9]/15 border border-[#2ee8c9]/40 text-[#2ee8c9] text-[11px] font-extrabold uppercase tracking-wider">
                          {w.status}
                        </span>
                      </div>
                      <div>
                        <h4 className="text-sm font-black text-white truncate">{w.currentJob?.title}</h4>
                        <p className="text-xs text-slate-300 truncate mt-0.5">{w.currentJob?.company}</p>
                      </div>
                      <div className="pt-2 border-t border-white/10 flex items-center justify-between text-[11px] text-slate-400 font-mono">
                        <span className="truncate max-w-[200px]">Step: <strong className="text-[#38bdf8] font-bold">{w.currentStep || "PROCESSING"}</strong></span>
                        <span>{w.startedAt ? new Date(w.startedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "Active"}</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          ) : activeJob ? (
            <div className="p-5 rounded-2xl border border-[#2ee8c9]/40 bg-gradient-to-r from-[#0a1622] via-[#0d1c2a] to-[#08121d] text-slate-200 shadow-2xl space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-black text-[#2ee8c9] uppercase tracking-widest flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-[#2ee8c9] animate-ping" />
                  Currently Processing
                </span>
                <span className="px-3 py-1 rounded-full bg-[#2ee8c9]/15 border border-[#2ee8c9]/40 text-[#2ee8c9] text-xs font-extrabold shadow-[0_0_10px_rgba(46,232,201,0.2)]">
                  Match {activeJob.matchScore}%
                </span>
              </div>
              <div>
                <h3 className="text-lg font-black text-white">{activeJob.title}</h3>
                <p className="text-xs text-slate-300 mt-0.5">{activeJob.company}</p>
              </div>
              <div className="pt-2 border-t border-white/10 flex items-center justify-between text-xs text-slate-400 font-mono">
                <span>Step: <strong className="text-[#38bdf8] font-bold">{activeJob.currentStep || "APPLYING"}</strong></span>
                <span>Started: {activeJob.applicationStartedAt ? new Date(activeJob.applicationStartedAt).toLocaleTimeString() : "Just now"}</span>
              </div>
            </div>
          ) : (
            <div className="p-4 rounded-xl bg-[#080d16] border border-white/5 flex items-center justify-between text-xs text-slate-400">
              <span className="flex items-center gap-2">
                <IconCheck className="w-4 h-4 text-[#2ee8c9]" />
                No job actively in execution. Ready for batch initiation.
              </span>
              <button
                onClick={() => handleStart()}
                className="text-[#2ee8c9] hover:underline font-bold cursor-pointer"
              >
                Start Run →
              </button>
            </div>
          )}

          {/* Recent Activity Timeline with Worker Tabs */}
          <RecentActivityPanel
            logs={recentLogs}
            workers={statusData?.workers}
            concurrency={statusData?.concurrency}
          />
        </div>

        {/* Right: System Health Panel (4 cols) */}
        <div className="lg:col-span-4">
          <SystemHealthPanel
            connected={Boolean(statusData && !error)}
            runnerStatus={statusData?.status || "READY"}
            repairCount={0}
            lastRepairEvent={null}
          />
        </div>
      </div>

      {/* Batch Config Modal */}
      <BatchConfigModal
        isOpen={showConfigModal}
        onClose={() => setShowConfigModal(false)}
        onStartRun={({ batchSize, concurrency, staggerDelay, selfHealing }) =>
          handleStart(batchSize, { concurrency, staggerDelay, selfHealing })
        }
        initialBatchSize={selectedBatchSize}
        loading={loading}
      />
    </div>
  );
}
