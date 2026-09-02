"use client";

import { useEffect, useState } from "react";
import { WorkflowPage } from "@/components/scaffold-page";
import { readApplicationCardStyle, saveApplicationCardStyle, type ApplicationCardStyle } from "@/components/application-assistant/application-card-preferences";
import { ApplicationQueueCard, type QueueApplication } from "@/components/application-assistant/application-queue-card";
import { resolveApplicationReadiness } from "@/components/application-assistant/application-readiness";

const CARD_STYLE_PREVIEW: QueueApplication = {
  id: "card-style-preview",
  companyName: "Northstar Labs",
  roleTitle: "Senior Software Engineer",
  provider: "CareerOS",
  status: "submitted_manually",
  progress: 1,
  verifiedCount: 8,
  reviewCount: 0,
  missingCount: 0,
  conflictingCount: 0,
  matchScore: 92,
  aiAnalyzed: true,
  updatedAt: "2026-09-01T12:00:00.000Z",
  quickApplyAvailable: true,
  errors: [],
};

export default function SettingsPage() {
  const [cardStyle, setCardStyle] = useState<ApplicationCardStyle>("compact");
  useEffect(() => setCardStyle(readApplicationCardStyle()), []);
  return (
    <WorkflowPage
      title="Settings"
      eyebrow="Foundation"
      subtitle="Control how CareerOS stores data, syncs with the extension, and protects your job search workspace."
      primaryAction={{ href: "/profile", label: "Review profile" }}
      secondaryAction={{ href: "/roadmap", label: "View roadmap" }}
      outcomes={[
        "Keep API, extension, and local workspace settings understandable.",
        "Make privacy and data ownership controls visible before they are urgent.",
        "Separate product preferences from application content.",
      ]}
      focusAreas={[
        {
          title: "Sync",
          description: "Connection status between web, API, and ApplyPilot.",
        },
        {
          title: "Privacy",
          description: "Export, delete, retention, and local-first controls.",
        },
        {
          title: "Defaults",
          description: "Workspace preferences, application behavior, and notification rhythm.",
        },
      ]}
    >
    <section className="dashboard-panel application-card-style-panel" aria-labelledby="application-card-style">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Appearance</span>
          <h2 id="application-card-style">Application card style</h2>
          <p className="muted dashboard-panel-copy">Choose the visual treatment used throughout your application views.</p>
        </div>
      </div>
      <div className="application-card-style-options">
        <button type="button" className={cardStyle === "compact" ? "application-card-style-option is-selected" : "application-card-style-option"} onClick={() => { setCardStyle("compact"); saveApplicationCardStyle("compact"); }}>
          <strong>Compact</strong><span>Clean, modern dark card</span>
        </button>
        <button type="button" className={cardStyle === "heritage" ? "application-card-style-option is-selected" : "application-card-style-option"} onClick={() => { setCardStyle("heritage"); saveApplicationCardStyle("heritage"); }}>
          <strong>Heritage</strong><span>Warm sculpted bronze treatment</span>
        </button>
        <button type="button" className={cardStyle === "holographic" ? "application-card-style-option is-selected" : "application-card-style-option"} onClick={() => { setCardStyle("holographic"); saveApplicationCardStyle("holographic"); }}>
          <strong>Holographic</strong><span>Layered sci-fi interface treatment</span>
        </button>
      </div>
      <div className="application-card-style-preview">
        <span className="toc-card-kicker">Live preview</span>
        <ApplicationQueueCard
          app={CARD_STYLE_PREVIEW}
          statusAccent="emerald"
          isOpening={false}
          isBrowserOpen={false}
          isAnalyzing={false}
          isWizardLoading={false}
          gateLoading={false}
          profileBlocked={false}
          readiness={resolveApplicationReadiness(CARD_STYLE_PREVIEW)}
          needsAiAnalysis={false}
          pendingCount={0}
          isPreparing={false}
          isActivePrep={false}
          openingElapsedSec={0}
          analyzeElapsedSec={0}
          closingBrowser={false}
          onFocusBrowser={() => undefined}
          onResume={() => undefined}
          onAnswerQuestions={() => undefined}
          onOpenInBrowser={() => undefined}
          onToggleSubmitted={() => undefined}
          onArchive={() => undefined}
          primaryActionOverride={{ label: "Preview", onClick: () => undefined }}
        />
      </div>
    </section>
    </WorkflowPage>
  );
}
