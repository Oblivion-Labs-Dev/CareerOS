"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { EnhancedDashboard } from "@/components/dashboard/enhanced-dashboard";
import { AutopilotControlCenter } from "@/components/application-assistant/autopilot/autopilot-control-center";
import { ApplicationAssistantDashboard } from "@/components/application-assistant/application-assistant-dashboard";
import { LatencyDiagnosticsCenter } from "@/components/application-assistant/latency-diagnostics-center";
import { RecruiterInbox } from "@/components/tracker/recruiter-inbox";
import { PipelineKanban } from "@/components/tracker/pipeline-kanban";
import styles from "@/components/application-assistant/autopilot/control-center.module.css";
import { CardStyleSwitch } from "@/components/ui/lab-kpi-card";
import { useCardStyle } from "@/hooks/use-card-style";

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
 * Overview (Night Batch controls + metrics) and the Applications workspace
 * always render together now, not as separate tabs — "Review" is just a
 * status filter inside Applications, and "Diagnostics" is its own page
 * (`/diagnostic`, linked from here rather than rendered inline). The old
 * `?tab=` links this map covers still resolve to something sensible so
 * nothing that linked into this page breaks, and the tracker/inbox/pipeline
 * surfaces remain reachable at their original query params.
 */
const CONTROL_CENTER_TABS: Record<string, "overview" | "applications" | "review" | "diagnostics"> = {
  autopilot: "overview",
  overview: "overview",
  applications: "applications",
  attention: "applications",
  progress: "applications",
  history: "applications",
  manual: "applications",
  rejected: "applications",
  ineligible: "applications",
  discovered: "applications",
  scored: "applications",
  applying: "applications",
  waiting: "applications",
  staged: "applications",
  needs_review: "applications",
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
  const [cardStyle, setCardStyle] = useCardStyle();

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

  // The old standalone Dashboard now lives here as a tab (/dashboard redirects
  // to ?tab=dashboard), so Autopilot is the one home page.
  const view = tab === "dashboard" ? "dashboard" : "autopilot";

  return (
    <div className="page-content aa-page max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-2 pb-12 font-sans">
      <div className={styles.viewBar}>
      <nav className={styles.viewSwitch} role="tablist" aria-label="Autopilot views">
        <Link
          href="/applications"
          role="tab"
          aria-selected={view === "autopilot"}
          className={styles.viewTab}
          data-active={view === "autopilot"}
        >
          Autopilot
        </Link>
        {/* Lab folds the dashboard's chart and outcome figures into the
            Autopilot view, so its separate tab only exists in Classic.
            ?tab=dashboard still resolves for old links. */}
        {cardStyle === "classic" || view === "dashboard" ? (
          <Link
            href="/applications?tab=dashboard"
            role="tab"
            aria-selected={view === "dashboard"}
            className={styles.viewTab}
            data-active={view === "dashboard"}
          >
            Dashboard
          </Link>
        ) : null}
      </nav>
      {view === "autopilot" ? <CardStyleSwitch value={cardStyle} onChange={setCardStyle} /> : null}
      </div>
      <Suspense fallback={<ApplicationQueueLoading />}>
        {view === "dashboard" ? (
          <EnhancedDashboard initialTopJobs={[]} />
        ) : (
          <AutopilotControlCenter initialSection={CONTROL_CENTER_TABS[tab] ?? "overview"} />
        )}
      </Suspense>
    </div>
  );
}
