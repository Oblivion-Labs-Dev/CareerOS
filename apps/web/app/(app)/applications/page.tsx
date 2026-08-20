"use client";

import { Suspense, useEffect, useState } from "react";
import { ApplicationAssistantDashboard } from "@/components/application-assistant/application-assistant-dashboard";
import { AutopilotDashboard } from "@/components/application-assistant/autopilot-dashboard";
import { ReviewCenter } from "@/components/application-assistant/review-center";
import { getAutopilotStatus, getStagedApplications } from "@/lib/application-assistant-api";
import { IconBolt, IconClock, IconInbox } from "@/components/application-assistant/autopilot/icons";

function ApplicationQueueLoading() {
  return (
    <div className="p-16 text-center" role="status" aria-label="Loading applications">
      <div className="inline-block w-8 h-8 rounded-full border-2 border-[#2ee8c9] border-t-transparent animate-spin mb-3" />
      <p className="text-xs text-slate-400 font-mono">Loading Autopilot Control Center…</p>
    </div>
  );
}

export default function ApplicationsPage() {
  const [activeTab, setActiveTab] = useState<"autopilot" | "review" | "tracker">("autopilot");
  const [stagedCount, setStagedCount] = useState<number>(0);
  const [isRunning, setIsRunning] = useState<boolean>(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [stagedRes, statusRes] = await Promise.all([
          getStagedApplications().catch(() => []),
          getAutopilotStatus().catch(() => null),
        ]);

        if (Array.isArray(stagedRes)) {
          setStagedCount(stagedRes.length);
        } else if (stagedRes?.staged && Array.isArray(stagedRes.staged)) {
          setStagedCount(stagedRes.staged.length);
        }

        if (statusRes?.running || statusRes?.status === "RUNNING" || statusRes?.status === "RECOVERING") {
          setIsRunning(true);
        } else {
          setIsRunning(false);
        }
      } catch {
        // Silently continue
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="page-content aa-page space-y-6 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-12 font-sans">
      {/* ─── Top Master Header (Matching Mockup 100%) ─── */}
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-5 border-b border-white/10 pb-5">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-black tracking-widest text-[#2ee8c9] uppercase">
              AUTOPILOT
            </span>
          </div>

          <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-white flex items-center gap-3">
            Job Applications & Autopilot
            <span
              className={`inline-flex h-3 w-3 rounded-full transition-all duration-300 ${
                isRunning
                  ? "bg-[#2ee8c9] shadow-[0_0_14px_rgba(46,232,201,0.9)] animate-ping"
                  : "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.7)]"
              }`}
            />
          </h1>

          <p className="text-xs sm:text-sm text-slate-300 max-w-2xl leading-relaxed">
            Autonomous nightly application runner with AI-powered matching, self-healing, and smart recovery.
          </p>
        </div>

        {/* ─── Top Right Navigation Tabs (Exact Color Scheme from Mockup) ─── */}
        <div className="flex items-center gap-3 self-start md:self-auto">
          {/* 1. Autopilot Button (Teal) */}
          <button
            onClick={() => setActiveTab("autopilot")}
            style={{
              background: activeTab === "autopilot" ? "#0d2a2a" : "#0c1820",
              borderColor: activeTab === "autopilot" ? "#2ee8c9" : "rgba(46, 232, 201, 0.4)",
              color: "#2ee8c9",
              boxShadow: activeTab === "autopilot" ? "0 0 20px rgba(46, 232, 201, 0.4)" : "none",
            }}
            className="px-4 py-2.5 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconBolt className="w-4 h-4 text-[#2ee8c9]" />
            <span>Autopilot</span>
          </button>

          {/* 2. Review Center Button (Purple / Violet) */}
          <button
            onClick={() => setActiveTab("review")}
            style={{
              background: activeTab === "review" ? "#23153c" : "#181128",
              borderColor: activeTab === "review" ? "#a855f7" : "rgba(168, 85, 247, 0.4)",
              color: "#c084fc",
              boxShadow: activeTab === "review" ? "0 0 20px rgba(168, 85, 247, 0.4)" : "none",
            }}
            className="px-4 py-2.5 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconClock className="w-4 h-4 text-[#c084fc]" />
            <span>Review Center</span>
            {stagedCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-black bg-[#a855f7] text-white shadow-sm">
                {stagedCount}
              </span>
            )}
          </button>

          {/* 3. All Applications Button (Amber / Gold) */}
          <button
            onClick={() => setActiveTab("tracker")}
            style={{
              background: activeTab === "tracker" ? "#2c1d0c" : "#1e1509",
              borderColor: activeTab === "tracker" ? "#f59e0b" : "rgba(245, 158, 11, 0.4)",
              color: "#fbbf24",
              boxShadow: activeTab === "tracker" ? "0 0 20px rgba(245, 158, 11, 0.4)" : "none",
            }}
            className="px-4 py-2.5 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconInbox className="w-4 h-4 text-[#fbbf24]" />
            <span>All Applications</span>
          </button>
        </div>
      </header>

      {/* ─── Main Tab Content ─── */}
      {activeTab === "autopilot" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <AutopilotDashboard onNavigateTab={(t) => setActiveTab(t)} />
        </Suspense>
      )}

      {activeTab === "review" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <ReviewCenter />
        </Suspense>
      )}

      {activeTab === "tracker" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <ApplicationAssistantDashboard />
        </Suspense>
      )}
    </div>
  );
}
