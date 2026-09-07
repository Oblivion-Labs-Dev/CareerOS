"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ApplicationAssistantDashboard } from "@/components/application-assistant/application-assistant-dashboard";
import { ApplyBoard } from "@/components/application-assistant/autopilot/apply-board";
import { FailedJobsCenter } from "@/components/application-assistant/failed-jobs-center";
import { ReviewCenter } from "@/components/application-assistant/review-center";
import { SubmittedJobsCenter } from "@/components/application-assistant/submitted-jobs-center";
import { SkippedJobsCenter } from "@/components/application-assistant/skipped-jobs-center";
import { LatencyDiagnosticsCenter } from "@/components/application-assistant/latency-diagnostics-center";
import { RecruiterInbox } from "@/components/tracker/recruiter-inbox";
import { PipelineKanban } from "@/components/tracker/pipeline-kanban";
import { getAutopilotJobs, getAutopilotStatus, getStagedApplications } from "@/lib/application-assistant-api";
import { IconActivity, IconAlertCircle, IconBolt, IconClock, IconInbox, IconSend } from "@/components/application-assistant/autopilot/icons";
import styles from "@/components/application-assistant/autopilot/autopilot-ui.module.css";

function ApplicationQueueLoading() {
  return (
    <div className={styles.loadingWrap} role="status" aria-label="Loading applications">
      <div className={styles.loadingRing}>
        <span className={styles.loadingRingOuter} />
        <span className={styles.loadingRingSpin} />
        <span className={styles.loadingRingGlow} />
        <span className={styles.loadingRingCore} />
      </div>
      <p className={styles.loadingLabel}>Preparing your workspace</p>
      <p className={styles.loadingSub}>Syncing the latest application activity.</p>
    </div>
  );
}

type ApplicationsTab = "autopilot" | "submitted" | "review" | "failed" | "skipped" | "tracker" | "inbox" | "pipeline" | "diagnostics";

const VALID_TABS: ApplicationsTab[] = [
  "autopilot",
  "submitted",
  "review",
  "failed",
  "skipped",
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
  const [skippedCount, setSkippedCount] = useState<number>(0);
  const [isRunning, setIsRunning] = useState<boolean>(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [stagedRes, submittedRes, failedRes, skippedRes, statusRes] = await Promise.all([
          getStagedApplications().catch(() => []),
          getAutopilotJobs("SUBMITTED").catch(() => ({ jobs: [] })),
          getAutopilotJobs("FAILED").catch(() => ({ jobs: [] })),
          getAutopilotJobs("SKIPPED").catch(() => ({ jobs: [] })),
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
        if (skippedRes?.jobs && Array.isArray(skippedRes.jobs)) {
          setSkippedCount(skippedRes.jobs.length);
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
      {/* ─── Top Master Header ─── */}
      <header className={styles.masterHeader}>
        <div className="space-y-1.5">
          <span className={styles.eyebrow}>AUTOPILOT</span>

          <h1 className={styles.heading}>
            Job Applications & Autopilot
            <span className={`${styles.liveDot} ${isRunning ? styles.liveDotRunning : ""}`} />
          </h1>

          <p className={styles.headerSubtitle}>
            Autonomous application runner with AI-powered matching, smart answering, and self-healing.
          </p>
        </div>

        {/* ─── Top Right Navigation Tabs ─── */}
        <nav className={styles.tabBar}>
          <button
            data-tab="autopilot"
            onClick={() => setActiveTab("autopilot")}
            className={`${styles.tabBtn} ${activeTab === "autopilot" ? styles.tabBtnActive : ""}`}
          >
            <IconBolt className="w-4 h-4" />
            <span>Autopilot</span>
          </button>

          <button
            data-tab="submitted"
            onClick={() => setActiveTab("submitted")}
            className={`${styles.tabBtn} ${activeTab === "submitted" ? styles.tabBtnActive : ""}`}
          >
            <IconSend className="w-4 h-4" />
            <span>Submitted</span>
            {submittedCount > 0 && <span className={styles.tabBadge}>{submittedCount}</span>}
          </button>

          <button
            data-tab="review"
            onClick={() => setActiveTab("review")}
            className={`${styles.tabBtn} ${activeTab === "review" ? styles.tabBtnActive : ""}`}
          >
            <IconClock className="w-4 h-4" />
            <span>In Review</span>
            {reviewCount > 0 && <span className={styles.tabBadge}>{reviewCount}</span>}
          </button>

          <button
            data-tab="failed"
            onClick={() => setActiveTab("failed")}
            className={`${styles.tabBtn} ${activeTab === "failed" ? styles.tabBtnActive : ""}`}
          >
            <IconAlertCircle className="w-4 h-4" />
            <span>Failed</span>
            {failedCount > 0 && <span className={styles.tabBadge}>{failedCount}</span>}
          </button>

          <button
            data-tab="skipped"
            onClick={() => setActiveTab("skipped")}
            className={`${styles.tabBtn} ${activeTab === "skipped" ? styles.tabBtnActive : ""}`}
          >
            <IconClock className="w-4 h-4" />
            <span>Skipped</span>
            {skippedCount > 0 && <span className={styles.tabBadge}>{skippedCount}</span>}
          </button>

          <button
            data-tab="tracker"
            onClick={() => setActiveTab("tracker")}
            className={`${styles.tabBtn} ${activeTab === "tracker" ? styles.tabBtnActive : ""}`}
          >
            <IconInbox className="w-4 h-4" />
            <span>All Applications</span>
          </button>

          <button
            data-tab="inbox"
            onClick={() => setActiveTab("inbox")}
            className={`${styles.tabBtn} ${activeTab === "inbox" ? styles.tabBtnActive : ""}`}
          >
            <IconInbox className="w-4 h-4" />
            <span>Inbox</span>
          </button>

          <button
            data-tab="pipeline"
            onClick={() => setActiveTab("pipeline")}
            className={`${styles.tabBtn} ${activeTab === "pipeline" ? styles.tabBtnActive : ""}`}
          >
            <IconActivity className="w-4 h-4" />
            <span>Pipeline</span>
          </button>

          <button
            data-tab="diagnostics"
            onClick={() => setActiveTab("diagnostics")}
            className={`${styles.tabBtn} ${activeTab === "diagnostics" ? styles.tabBtnActive : ""}`}
          >
            <IconActivity className="w-4 h-4" />
            <span>Diagnostics</span>
          </button>
        </nav>
      </header>

      {/* ─── Main Content ─── */}
      {activeTab === "autopilot" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <ApplyBoard />
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

      {activeTab === "skipped" && (
        <Suspense fallback={<ApplicationQueueLoading />}>
          <SkippedJobsCenter />
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
