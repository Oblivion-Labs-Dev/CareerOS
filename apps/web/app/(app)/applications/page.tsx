"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ApplicationAssistantDashboard } from "@/components/application-assistant/application-assistant-dashboard";
import { AutopilotDashboard } from "@/components/application-assistant/autopilot-dashboard";
import { FailedJobsCenter } from "@/components/application-assistant/failed-jobs-center";
import { ReviewCenter } from "@/components/application-assistant/review-center";
import { SubmittedJobsCenter } from "@/components/application-assistant/submitted-jobs-center";
import { LatencyDiagnosticsCenter } from "@/components/application-assistant/latency-diagnostics-center";
import { RecruiterInbox } from "@/components/tracker/recruiter-inbox";
import { PipelineKanban } from "@/components/tracker/pipeline-kanban";
import { getAutopilotJobs, getAutopilotStatus, getStagedApplications } from "@/lib/application-assistant-api";
import { IconActivity, IconAlertCircle, IconBolt, IconClock, IconInbox, IconSend } from "@/components/application-assistant/autopilot/icons";

function ApplicationQueueLoading() {
  return (
    <div className="flex min-h-[360px] flex-col items-center justify-center p-16 text-center" role="status" aria-label="Loading applications">
      <div className="relative mb-5 flex h-16 w-16 items-center justify-center">
        <span className="absolute inset-0 rounded-full border border-cyan-300/20" />
        <span className="absolute inset-2 rounded-full border border-cyan-300/40 border-t-cyan-200 animate-spin" />
        <span className="absolute inset-5 rounded-full bg-cyan-300/10 shadow-[0_0_24px_rgba(103,232,249,0.22)] animate-pulse" />
        <span className="relative h-2.5 w-2.5 rounded-full bg-cyan-200 shadow-[0_0_14px_rgba(103,232,249,0.9)]" />
      </div>
      <p className="text-xs font-semibold tracking-[0.14em] text-slate-300 uppercase">Preparing your workspace</p>
      <p className="mt-2 text-xs text-slate-500">Syncing the latest application activity.</p>
    </div>
  );
}

type ApplicationsTab = "autopilot" | "submitted" | "review" | "failed" | "tracker" | "inbox" | "pipeline" | "diagnostics";

const VALID_TABS: ApplicationsTab[] = [
  "autopilot",
  "submitted",
  "review",
  "failed",
  "tracker",
  "inbox",
  "pipeline",
  "diagnostics",
];

export default function ApplicationsPage() {
  return (
    <Suspense fallback={<ApplicationQueueLoading />}>
      <ApplicationsPageInner />
    </Suspense>
  );
}

function ApplicationsPageInner() {
  const searchParams = useSearchParams();
  const initialTab = (() => {
    const requested = searchParams.get("tab");
    return requested && (VALID_TABS as string[]).includes(requested) ? (requested as ApplicationsTab) : "autopilot";
  })();
  const [activeTab, setActiveTab] = useState<ApplicationsTab>(initialTab);
  const [reviewCount, setReviewCount] = useState<number>(0);
  const [submittedCount, setSubmittedCount] = useState<number>(0);
  const [failedCount, setFailedCount] = useState<number>(0);
  const [isRunning, setIsRunning] = useState<boolean>(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [stagedRes, submittedRes, failedRes, statusRes] = await Promise.all([
          getStagedApplications().catch(() => []),
          getAutopilotJobs("SUBMITTED").catch(() => ({ jobs: [] })),
          getAutopilotJobs("FAILED").catch(() => ({ jobs: [] })),
          getAutopilotStatus().catch(() => null),
        ]);

        if (Array.isArray(stagedRes)) {
          setReviewCount(stagedRes.length);
        } else if (stagedRes?.staged && Array.isArray(stagedRes.staged)) {
          setReviewCount(stagedRes.staged.length);
        }

        if (submittedRes?.jobs && Array.isArray(submittedRes.jobs)) {
          setSubmittedCount(submittedRes.jobs.length);
        }
        if (failedRes?.jobs && Array.isArray(failedRes.jobs)) {
          setFailedCount(failedRes.jobs.length);
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
            Autonomous application runner with AI-powered matching, smart answering, and self-healing.
          </p>
        </div>

        {/* ─── Top Right Navigation Tabs ─── */}
        <div className="flex flex-wrap items-center gap-2.5 self-start md:self-auto">
          {/* 1. Autopilot Button (Teal) */}
          <button
            onClick={() => setActiveTab("autopilot")}
            style={{
              background: activeTab === "autopilot" ? "#0d2a2a" : "#0c1820",
              borderColor: activeTab === "autopilot" ? "#2ee8c9" : "rgba(46, 232, 201, 0.4)",
              color: "#2ee8c9",
              boxShadow: activeTab === "autopilot" ? "0 0 20px rgba(46, 232, 201, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconBolt className="w-4 h-4 text-[#2ee8c9]" />
            <span>Autopilot</span>
          </button>

          {/* 2. Submitted Button (Emerald) */}
          <button
            onClick={() => setActiveTab("submitted")}
            style={{
              background: activeTab === "submitted" ? "#0a241b" : "#081813",
              borderColor: activeTab === "submitted" ? "#34d399" : "rgba(52, 211, 153, 0.4)",
              color: "#34d399",
              boxShadow: activeTab === "submitted" ? "0 0 20px rgba(52, 211, 153, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconSend className="w-4 h-4 text-[#34d399]" />
            <span>Submitted</span>
            {submittedCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-black bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 shadow-sm">
                {submittedCount}
              </span>
            )}
          </button>

          {/* 3. Review Center Button (Purple / Violet) */}
          <button
            onClick={() => setActiveTab("review")}
            style={{
              background: activeTab === "review" ? "#23153c" : "#181128",
              borderColor: activeTab === "review" ? "#a855f7" : "rgba(168, 85, 247, 0.4)",
              color: "#c084fc",
              boxShadow: activeTab === "review" ? "0 0 20px rgba(168, 85, 247, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconClock className="w-4 h-4 text-[#c084fc]" />
            <span>In Review</span>
            {reviewCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-black bg-[#a855f7] text-white shadow-sm">
                {reviewCount}
              </span>
            )}
          </button>

          {/* 4. Failed Applications Button */}
          <button
            onClick={() => setActiveTab("failed")}
            style={{
              background: activeTab === "failed" ? "#2a0d14" : "#19080c",
              borderColor: activeTab === "failed" ? "#f43f5e" : "rgba(244, 63, 94, 0.4)",
              color: "#fb7185",
              boxShadow: activeTab === "failed" ? "0 0 20px rgba(244, 63, 94, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconAlertCircle className="w-4 h-4 text-[#fb7185]" />
            <span>Failed</span>
            {failedCount > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-black bg-rose-500/30 text-rose-300 border border-rose-500/40 shadow-sm">
                {failedCount}
              </span>
            )}
          </button>

          {/* 5. All Applications Button (Amber / Gold) */}
          <button
            onClick={() => setActiveTab("tracker")}
            style={{
              background: activeTab === "tracker" ? "#2c1d0c" : "#1e1509",
              borderColor: activeTab === "tracker" ? "#f59e0b" : "rgba(245, 158, 11, 0.4)",
              color: "#fbbf24",
              boxShadow: activeTab === "tracker" ? "0 0 20px rgba(245, 158, 11, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconInbox className="w-4 h-4 text-[#fbbf24]" />
            <span>All Applications</span>
          </button>

          {/* 6. Inbox Button (Indigo) */}
          <button
            onClick={() => setActiveTab("inbox")}
            style={{
              background: activeTab === "inbox" ? "#181d3c" : "#0e1122",
              borderColor: activeTab === "inbox" ? "#818cf8" : "rgba(129, 140, 248, 0.4)",
              color: "#a5b4fc",
              boxShadow: activeTab === "inbox" ? "0 0 20px rgba(129, 140, 248, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconInbox className="w-4 h-4 text-[#a5b4fc]" />
            <span>Inbox</span>
          </button>

          {/* 7. Pipeline Button (Lime) */}
          <button
            onClick={() => setActiveTab("pipeline")}
            style={{
              background: activeTab === "pipeline" ? "#1c2410" : "#12160a",
              borderColor: activeTab === "pipeline" ? "#a3e635" : "rgba(163, 230, 53, 0.4)",
              color: "#bef264",
              boxShadow: activeTab === "pipeline" ? "0 0 20px rgba(163, 230, 53, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconActivity className="w-4 h-4 text-[#bef264]" />
            <span>Pipeline</span>
          </button>

          {/* 8. Diagnostics Button (Cyan / Blue) */}
          <button
            onClick={() => setActiveTab("diagnostics")}
            style={{
              background: activeTab === "diagnostics" ? "#0f2231" : "#0a1722",
              borderColor: activeTab === "diagnostics" ? "#38bdf8" : "rgba(56, 189, 248, 0.4)",
              color: "#38bdf8",
              boxShadow: activeTab === "diagnostics" ? "0 0 20px rgba(56, 189, 248, 0.4)" : "none",
            }}
            className="px-3.5 py-2 text-xs font-black rounded-xl border transition-all duration-300 flex items-center gap-2 cursor-pointer hover:scale-[1.02] active:scale-[0.98]"
          >
            <IconActivity className="w-4 h-4 text-[#38bdf8]" />
            <span>Diagnostics</span>
          </button>
        </div>
      </header>

      {/* ─── Main Content ─── */}
      {activeTab === "autopilot" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <AutopilotDashboard onNavigateTab={(t) => setActiveTab(t)} />
        </Suspense>
      )}

      {activeTab === "submitted" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <SubmittedJobsCenter />
        </Suspense>
      )}

      {activeTab === "review" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <ReviewCenter />
        </Suspense>
      )}

      {activeTab === "failed" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <FailedJobsCenter
            onReprocessSuccess={() => setActiveTab("autopilot")}
            onOpenPrep={() => setActiveTab("tracker")}
          />
        </Suspense>
      )}

      {activeTab === "tracker" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <ApplicationAssistantDashboard />
        </Suspense>
      )}

      {activeTab === "inbox" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <RecruiterInbox />
        </Suspense>
      )}

      {activeTab === "pipeline" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <PipelineKanban />
        </Suspense>
      )}

      {activeTab === "diagnostics" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <LatencyDiagnosticsCenter />
        </Suspense>
      )}
    </div>
  );
}
