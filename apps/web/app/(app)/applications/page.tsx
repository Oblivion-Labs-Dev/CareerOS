"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AutopilotControlCenter } from "@/components/application-assistant/autopilot/autopilot-control-center";
import { ApplicationAssistantDashboard } from "@/components/application-assistant/application-assistant-dashboard";
import { LatencyDiagnosticsCenter } from "@/components/application-assistant/latency-diagnostics-center";
import { RecruiterInbox } from "@/components/tracker/recruiter-inbox";
import { PipelineKanban } from "@/components/tracker/pipeline-kanban";
import styles from "@/components/application-assistant/autopilot/control-center.module.css";

function ApplicationQueueLoading() {
  return (
    <div className={styles.loadingText} role="status" aria-label="Loading Autopilot">
      Loading Autopilot…
    </div>
  );
}

/**
 * Autopilot = operational control center for the autonomous applier.
 * Broader career analytics stay on the main CareerOS Dashboard.
 *
 * The control center owns four sections (Overview / Applications / Review /
 * Diagnostics). The pre-redesign per-status tabs are now filters inside
 * Applications, but their old `?tab=` links still resolve here so nothing that
 * linked into this page breaks — and the tracker/inbox/pipeline surfaces remain
 * reachable at their original query params.
 */
const CONTROL_CENTER_TABS: Record<string, "overview" | "applications" | "review" | "diagnostics"> = {
  autopilot: "overview",
  overview: "overview",
  applications: "applications",
  queued: "applications",
  submitted: "applications",
  failed: "applications",
  skipped: "applications",
  review: "review",
  diagnostics: "diagnostics",
};

export default function ApplicationsPage() {
  return (
    <Suspense fallback={<ApplicationQueueLoading />}>
      <ApplicationsPageInner />
    </Suspense>
  );
}

function ApplicationsPageInner() {
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") || "autopilot";

  // Legacy standalone surfaces kept intact at their original routes.
  if (tab === "tracker") {
    return (
      <div className="page-content aa-page max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-12 font-sans">
        <Suspense fallback={<ApplicationQueueLoading />}>
          <ApplicationAssistantDashboard />
        </Suspense>
      </div>
    );
  }
  if (tab === "inbox") {
    return (
      <div className="page-content aa-page max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-12 font-sans">
        <Suspense fallback={<ApplicationQueueLoading />}>
          <RecruiterInbox />
        </Suspense>
      </div>
    );
  }
  if (tab === "pipeline") {
    return (
      <div className="page-content aa-page max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-12 font-sans">
        <Suspense fallback={<ApplicationQueueLoading />}>
          <PipelineKanban />
        </Suspense>
      </div>
    );
  }
  if (tab === "latency") {
    return (
      <div className="page-content aa-page max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-12 font-sans">
        <Suspense fallback={<ApplicationQueueLoading />}>
          <LatencyDiagnosticsCenter />
        </Suspense>
      </div>
    );
  }

  return (
    <div className="page-content aa-page max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-12 font-sans">
      <Suspense fallback={<ApplicationQueueLoading />}>
        <AutopilotControlCenter initialSection={CONTROL_CENTER_TABS[tab] ?? "overview"} />
      </Suspense>
    </div>
  );
}
