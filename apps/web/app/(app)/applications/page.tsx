"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApplicationAssistantDashboard } from "@/components/application-assistant/application-assistant-dashboard";
import { AutopilotDashboard } from "@/components/application-assistant/autopilot-dashboard";
import { ReviewCenter } from "@/components/application-assistant/review-center";

type ApplicationsTab = "autopilot" | "review" | "tracker";

function ApplicationQueueLoading() {
  return (
    <div className="autopilot-loading" role="status" aria-label="Loading applications">
      <span />
      Loading CareerOS workspace…
    </div>
  );
}

function ApplicationsWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const activeTab: ApplicationsTab = requestedTab === "review" || requestedTab === "tracker"
    ? requestedTab
    : "autopilot";

  const navigateTab = (tab: ApplicationsTab) => {
    router.replace(tab === "autopilot" ? "/applications" : `/applications?tab=${tab}`, { scroll: false });
  };

  return (
    <div className={`applications-control-page applications-control-page--${activeTab}`}>
      {activeTab === "autopilot" ? (
        <AutopilotDashboard onNavigateTab={navigateTab} />
      ) : (
        <section className="applications-secondary-workspace">
          <header className="applications-secondary-header">
            <div>
              <span>{activeTab === "review" ? "Review Center" : "Application history"}</span>
              <h1>{activeTab === "review" ? "Applications awaiting your review" : "All Applications"}</h1>
              <p>
                {activeTab === "review"
                  ? "Resolve the decisions that require human judgment, then return them to Autopilot."
                  : "Inspect every application, checkpoint, outcome, and submission state."}
              </p>
            </div>
            <button type="button" className="autopilot-button autopilot-button--secondary" onClick={() => navigateTab("autopilot")}>
              Back to Autopilot
            </button>
          </header>
          {activeTab === "review" ? <ReviewCenter /> : <ApplicationAssistantDashboard />}
        </section>
      )}
    </div>
  );
}

export default function ApplicationsPage() {
  return (
    <Suspense fallback={<ApplicationQueueLoading />}>
      <ApplicationsWorkspace />
    </Suspense>
  );
}
