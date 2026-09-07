"use client";

import { useEffect, useRef, useState } from "react";
import { SidePanelPortal } from "@/components/side-panel-portal";
import {
  resolveApplicationStage,
  resolvePrimaryAction,
  resolveQuickApplyHint,
  type ResolvedReadiness,
} from "./application-readiness";
import "./application-queue-card.css";
import { APPLICATION_CARD_STYLE_EVENT, readApplicationCardStyle, type ApplicationCardStyle } from "./application-card-preferences";

export type QueueApplication = {
  id: string;
  companyName: string;
  roleTitle: string;
  provider: string;
  status: string;
  progress: number;
  verifiedCount: number;
  reviewCount: number;
  missingCount: number;
  conflictingCount: number;
  pendingFieldCount?: number;
  readyForBrowser?: boolean;
  aiAnalyzed?: boolean;
  matchScore?: number;
  updatedAt: string;
  resumeId?: string;
  resumeFileUsed?: string;
  jobLocation?: string;
  workplaceType?: string;
  errors: { error?: string; type?: string }[];
  skipped?: { field?: string; reason?: string }[];
  prepLog?: Record<string, unknown> | null;
  browserPlan?: { fillActions?: unknown[]; savedAt?: string; actionCount?: number } | null;
  jobId?: string;
  hasSavedAutofillState?: boolean;
  autofillStepCount?: number;
  prepRequired?: boolean;
  quickApplyAvailable?: boolean;
  quickApplyMode?: "focus" | "replay" | "slow" | "none" | "rebuild";
  quickApplyStepCount?: number;
  quickApplyLabel?: string;
  stoppedReason?: string;
  lastPrepFailed?: boolean;
  lastPrepError?: string;
  lastPrepAnalysis?: string;
  fields?: { label?: string; normalizedKey?: string; fieldType?: string; classification?: string }[];
  answers?: Record<string, any>;
};

type ReviewSessionStatus = {
  status: string;
  message: string;
  browserOpen: boolean;
  pendingFieldCount?: number;
};

const STATUS_LABELS: Record<string, string> = {
  ready_to_prepare: "Ready",
  in_progress: "In progress",
  needs_review: "Quick apply",
  blocked: "Blocked",
  ready_for_final_review: "Final review",
  submitted_manually: "Submitted",
  archived: "Archived",
};

const BRAND_COLORS: Record<string, string> = {
  microsoft: "#0078d4",
  reddit: "#ff4500",
  google: "#4285f4",
  meta: "#0668E1",
  apple: "#555555",
  amazon: "#ff9900",
  netflix: "#e50914",
};

function companyMonogram(name: string): string {
  return name.split(/\s+/).filter(Boolean)[0]?.[0]?.toUpperCase() ?? "?";
}

function companyColor(name: string): string {
  const key = name.toLowerCase().replace(/[^a-z]/g, "");
  for (const [brand, color] of Object.entries(BRAND_COLORS)) {
    if (key.includes(brand)) return color;
  }
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  const hues = [210, 250, 170, 30, 280];
  return `hsl(${hues[Math.abs(hash) % hues.length]} 48% 52%)`;
}

function formatRelativeTime(iso: string): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diffMin = Math.max(0, Math.floor((Date.now() - then) / 60000));
  if (diffMin < 1) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

function formatAppError(err: QueueApplication["errors"][number] | undefined): string {
  if (!err) return "Error";
  if (typeof err === "string") return err;
  if (typeof err.error === "string") return err.error;
  return "Error";
}

function fieldTotal(app: QueueApplication): number {
  const fromFields = app.fields?.length ?? 0;
  if (fromFields > 0) return fromFields;
  const sum = app.verifiedCount + app.reviewCount + app.missingCount + app.conflictingCount;
  return sum > 0 ? sum : 0;
}

function getActionAlert(opts: {
  app: QueueApplication;
  readiness: ResolvedReadiness;
}): { text: string; tone: "warn" | "bad" | "info"; action?: "answer" } | null {
  const { app, readiness } = opts;
  if (app.status === "submitted_manually" || app.status === "archived") {
    return null;
  }
  const { profileBlocked, pendingCount } = readiness;

  if (profileBlocked && pendingCount > 0) {
    return {
      text: `${pendingCount} profile answer${pendingCount === 1 ? "" : "s"} needed`,
      tone: "warn",
      action: "answer",
    };
  }
  if (app.reviewCount > 0) {
    return {
      text: `${app.reviewCount} answer${app.reviewCount === 1 ? "" : "s"} need review`,
      tone: "warn",
    };
  }
  if (app.missingCount > 0) {
    return {
      text: `${app.missingCount} field${app.missingCount === 1 ? "" : "s"} missing`,
      tone: "bad",
      action: profileBlocked ? "answer" : undefined,
    };
  }
  if (app.conflictingCount > 0) {
    return {
      text: `${app.conflictingCount} conflict${app.conflictingCount === 1 ? "" : "s"} to resolve`,
      tone: "warn",
    };
  }
  if (app.errors?.length) {
    return { text: formatAppError(app.errors[0]), tone: "bad" };
  }
  if (app.lastPrepFailed) {
    const hint = app.lastPrepError?.trim() || app.lastPrepAnalysis?.trim();
    return {
      text: hint ? `Prep failed — ${hint}` : "Prep failed — click Retry prep",
      tone: "bad",
    };
  }
  if (app.stoppedReason?.trim()) {
    return { text: app.stoppedReason.trim(), tone: "warn" };
  }
  return null;
}

type StageId = "queued" | "prepare" | "review" | "apply" | "done";

const PIPELINE_STAGES: { id: StageId; short: string }[] = [
  { id: "queued", short: "Discovered" },
  { id: "prepare", short: "Prepared" },
  { id: "apply", short: "Applied" },
  { id: "done", short: "Response" },
];

const CARD_STATUS: Record<string, { label: string; tone: string }> = {
  submitted_manually: { label: "Submitted", tone: "emerald" },
  needs_review: { label: "Ready", tone: "blue" },
  ready_for_final_review: { label: "In review", tone: "violet" },
  ready_to_prepare: { label: "Queued", tone: "blue" },
  in_progress: { label: "In review", tone: "violet" },
  in_review: { label: "In review", tone: "amber" },
  blocked: { label: "Needs action", tone: "amber" },
  failed: { label: "Failed", tone: "rose" },
  archived: { label: "Draft", tone: "slate" },
};

export function StatusBadge({ status, fallbackTone }: { status: string; fallbackTone: string }) {
  const value = CARD_STATUS[status] ?? { label: STATUS_LABELS[status] ?? "Queued", tone: fallbackTone };
  return <span className={`aac-status-badge aac-status-badge--${value.tone}`}><i aria-hidden />{value.label}</span>;
}

function formatTimelineDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

export function MatchRing({ score, tone }: { score?: number; tone: string }) {
  if (score == null) return null;
  const value = Math.max(0, Math.min(100, Math.round(score)));
  return (
    <span className={`aac-match-ring aac-match-ring--${tone}`} style={{ "--match-progress": `${value * 3.6}deg` } as React.CSSProperties} aria-label={`${value}% match`}>
      <strong>{value}%</strong><small>Match</small>
    </span>
  );
}

export function ApplicationMeta({ location, workplace, provider }: { location?: string; workplace?: string; provider?: string }) {
  const items = [location, workplace, provider].filter(Boolean);
  if (!items.length) return null;
  return <p className="aac-job-meta">{items.map((item, index) => <span key={`${item}-${index}`}>{index === 0 ? "⌖" : index === 1 ? "◷" : "◈"} {item}</span>)}</p>;
}

function formatTimelineLabel(
  stage: { index: number; label: string },
  opts: { isPrepBusy: boolean; prepElapsedSec: number; isAnalyzing: boolean; analyzeElapsedSec: number; isOpening: boolean; openingElapsedSec: number },
): string {
  const { isPrepBusy, prepElapsedSec, isAnalyzing, analyzeElapsedSec, isOpening, openingElapsedSec } = opts;
  if (isPrepBusy) {
    return prepElapsedSec > 0 ? `Preparing · ${prepElapsedSec}s` : "Preparing…";
  }
  if (isAnalyzing) {
    return analyzeElapsedSec > 0 ? `Analyzing · ${analyzeElapsedSec}s` : stage.label;
  }
  if (isOpening) {
    return openingElapsedSec > 0 ? `Applying · ${openingElapsedSec}s` : "Applying…";
  }
  return stage.label;
}

export function ApplicationTimeline({
  stageIndex,
  stageLabel,
  accent,
  completedDate,
  isPrepBusy = false,
  isApplying = false,
}: {
  stageIndex: number;
  stageLabel: string;
  accent: string;
  completedDate?: string;
  isPrepBusy?: boolean;
  isApplying?: boolean;
}) {
  const timelineBusy = isPrepBusy || isApplying;
  return (
    <div
      className={`aac-timeline aac-timeline--${accent}${timelineBusy ? " aac-timeline--preparing" : ""}`}
      aria-label={`Application stage: ${stageLabel}`}
    >
      <ol className="aac-timeline-track">
        {PIPELINE_STAGES.map((stage, index) => {
          const normalizedStage = Math.min(stageIndex, PIPELINE_STAGES.length - 1);
          const state = index < normalizedStage ? "done" : index === normalizedStage ? "current" : "upcoming";
          const showPrepSpinner = isPrepBusy && stage.id === "prepare" && index === stageIndex;
          const showApplySpinner = isApplying && stage.id === "apply" && index === stageIndex;
          const showSpinner = showPrepSpinner || showApplySpinner;
          return (
            <li key={stage.id} className={`aac-timeline-step aac-timeline-step--${state}`}>
              {showSpinner ? (
                <span className="aac-timeline-node aac-timeline-node--spinner" aria-hidden />
              ) : (
                <span className="aac-timeline-node" aria-hidden />
              )}
              <span className="aac-timeline-label">{stage.short}</span>
              <span className="aac-timeline-date">{state === "done" ? completedDate || "—" : state === "current" ? "Current" : "—"}</span>
            </li>
          );
        })}
      </ol>
      <p
        className="aac-timeline-current"
        role={timelineBusy ? "status" : undefined}
        aria-live={timelineBusy ? "polite" : undefined}
      >
        {stageLabel}
      </p>
    </div>
  );
}

export type ApplicationQueueCardProps = {
  app: QueueApplication;
  statusAccent: string;
  reviewSession?: ReviewSessionStatus;
  isOpening: boolean;
  isBrowserOpen: boolean;
  isAnalyzing: boolean;
  isWizardLoading: boolean;
  gateLoading: boolean;
  profileBlocked: boolean;
  readiness: ResolvedReadiness;
  needsAiAnalysis: boolean;
  pendingCount: number;
  isPreparing: boolean;
  isActivePrep: boolean;
  prepElapsedSec?: number;
  openingElapsedSec: number;
  analyzeElapsedSec: number;
  closingBrowser: boolean;
  onFocusBrowser: () => void;
  onResume: () => void;
  onAnswerQuestions: () => void;
  onOpenInBrowser: () => void;
  onToggleSubmitted: (submitted: boolean) => void;
  onArchive: () => void;
  onUnarchive?: () => void;
  onCloseBrowser?: () => void;
  prepReportSlot?: React.ReactNode;
  gateSlot?: React.ReactNode;
  reviewBannerSlot?: React.ReactNode;
  errorSlot?: React.ReactNode;
  intelligenceSlot?: React.ReactNode;
  primaryActionOverride?: { label: string; onClick: () => void; disabled?: boolean };
  drawerContentSlot?: React.ReactNode;
};

export function ApplicationQueueCard({
  app,
  statusAccent,
  reviewSession,
  isOpening,
  isBrowserOpen,
  isAnalyzing,
  isWizardLoading,
  gateLoading,
  profileBlocked,
  readiness,
  needsAiAnalysis,
  pendingCount,
  isPreparing,
  isActivePrep,
  prepElapsedSec = 0,
  openingElapsedSec,
  analyzeElapsedSec,
  closingBrowser,
  onFocusBrowser,
  onResume,
  onAnswerQuestions,
  onOpenInBrowser,
  onToggleSubmitted,
  onArchive,
  onUnarchive,
  onCloseBrowser,
  prepReportSlot,
  gateSlot,
  reviewBannerSlot,
  errorSlot,
  intelligenceSlot,
  primaryActionOverride,
  drawerContentSlot,
}: ApplicationQueueCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [cardStyle, setCardStyle] = useState<ApplicationCardStyle>("compact");
  const wrapRef = useRef<HTMLDivElement>(null);

  const updated = formatRelativeTime(app.updatedAt);
  const location = app.jobLocation?.trim();
  const workplace = app.workplaceType?.trim();
  const providerLabel = app.provider ? app.provider.charAt(0).toUpperCase() + app.provider.slice(1) : "Unknown";
  const totalFields = fieldTotal(app);
  const readyFields = app.verifiedCount;
  const stage = resolveApplicationStage({
    app,
    readiness,
    isPreparing,
    isActivePrep,
    isOpening,
    isBrowserOpen,
    lastPrepFailed: Boolean(app.lastPrepFailed),
  });
  const isApplying = isOpening && readiness.canQuickApply;
  const isPrepBusy = isPreparing || isActivePrep;
  const cardBusy = isPrepBusy || isApplying;
  const timelineLabel = formatTimelineLabel(stage, {
    isPrepBusy,
    prepElapsedSec,
    isAnalyzing,
    analyzeElapsedSec,
    isOpening,
    openingElapsedSec,
  });

  const actionAlert = getActionAlert({ app, readiness });
  const quickApplyHint = resolveQuickApplyHint(app, readiness, { isPreparing: isPrepBusy });
  const isSubmitted = app.status === "submitted_manually";
  const isArchived = app.status === "archived";

  const primary = resolvePrimaryAction({
    readiness,
    appStatus: app.status,
    isPreparing,
    isActivePrep,
    isOpening,
    isAnalyzing,
    isBrowserOpen,
    isWizardLoading,
    openingElapsedSec,
    analyzeElapsedSec,
    prepElapsedSec,
    lastPrepFailed: Boolean(app.lastPrepFailed),
  });

  const handlePrimary = (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!primary || primary.disabled) return;
    if (primary.kind === "start") { onResume(); return; }
    if (primary.kind === "questions") { onAnswerQuestions(); return; }
    if (primary.kind === "quick_apply") { onOpenInBrowser(); return; }
    if (primary.kind === "focus") { onFocusBrowser(); return; }
  };

  const handleAnswerAlert = (event: React.MouseEvent) => {
    event.stopPropagation();
    onAnswerQuestions();
  };

  const stopBubble = (event: React.MouseEvent) => {
    event.stopPropagation();
  };

  const openDrawer = () => setDrawerOpen(true);

  const agentNote = (() => {
    if (app.quickApplyLabel) return app.quickApplyLabel;
    const filled = app.prepLog?.filledCount ?? app.verifiedCount;
    if (!filled || !updated) return null;
    return `Verified ${filled} field${filled === 1 ? "" : "s"} · ${updated}`;
  })();

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (wrapRef.current?.contains(target) && !(target as HTMLElement).closest(".aac-menu-wrap")) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [menuOpen]);

  const closeDrawer = () => setDrawerOpen(false);

  useEffect(() => {
    const syncStyle = () => setCardStyle(readApplicationCardStyle());
    syncStyle();
    window.addEventListener(APPLICATION_CARD_STYLE_EVENT, syncStyle);
    return () => window.removeEventListener(APPLICATION_CARD_STYLE_EVENT, syncStyle);
  }, []);

  return (
    <div
      ref={wrapRef}
      className={`aac-wrap${isBrowserOpen ? " aac-wrap--live" : ""}`}
    >
      {gateSlot}
      <article
        className={`aac-card aac-card--${cardStyle} aac-card--${statusAccent}${isBrowserOpen ? " aac-card--live" : ""}${isAnalyzing ? " aac-card--busy" : ""}${cardBusy ? " aac-card--preparing" : ""}`}
        onClick={openDrawer}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openDrawer();
          }
        }}
        role="button"
        tabIndex={0}
        aria-label={`${app.companyName} application, ${timelineLabel}. Click for details.`}
      >
        <div className="aac-card-body">
        <header className="aac-head">
          <div className="aac-head-main">
            <span
              className="aac-logo"
              style={{ "--brand-color": companyColor(app.companyName) } as React.CSSProperties}
              aria-hidden
            >
              {companyMonogram(app.companyName)}
            </span>
            <StatusBadge status={app.status} fallbackTone={statusAccent} />
          </div>
          <div className="aac-menu-wrap" onClick={stopBubble}>
            <button
              type="button"
              className="aac-menu-btn"
              aria-label="More actions"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
                <circle cx="7" cy="2.5" r="1.2" fill="currentColor" />
                <circle cx="7" cy="7" r="1.2" fill="currentColor" />
                <circle cx="7" cy="11.5" r="1.2" fill="currentColor" />
              </svg>
            </button>
            {menuOpen && (
              <div className="aac-menu">
                {!isSubmitted && !isArchived && !isBrowserOpen && readiness.canQuickApply && (
                  <button type="button" onClick={() => { setMenuOpen(false); onOpenInBrowser(); }} disabled={isOpening || isAnalyzing}>
                    Quick apply
                  </button>
                )}
                {!isSubmitted && !isArchived && !isBrowserOpen && !readiness.canQuickApply && app.lastPrepFailed && (
                  <button type="button" onClick={() => { setMenuOpen(false); onResume(); }} disabled={isOpening || isAnalyzing || isPreparing || isActivePrep}>
                    Retry prep
                  </button>
                )}
                {!isSubmitted && !isArchived && isBrowserOpen && readiness.canQuickApply && (
                  <button type="button" onClick={() => { setMenuOpen(false); onOpenInBrowser(); }}>
                    Quick apply
                  </button>
                )}
                {isBrowserOpen && !readiness.canQuickApply && (
                  <button type="button" onClick={() => { setMenuOpen(false); onFocusBrowser(); }}>
                    Focus browser
                  </button>
                )}
                {isBrowserOpen && onCloseBrowser && (
                  <button type="button" onClick={() => { setMenuOpen(false); onCloseBrowser(); }} disabled={closingBrowser}>
                    Close browser
                  </button>
                )}
                <button type="button" onClick={() => { setMenuOpen(false); setDrawerOpen(true); }}>
                  View details
                </button>
                {!isArchived && app.status !== "submitted_manually" && (
                  <button type="button" onClick={() => { setMenuOpen(false); onToggleSubmitted(true); }}>
                    Mark submitted
                  </button>
                )}
                {app.status === "submitted_manually" && (
                  <button type="button" onClick={() => { setMenuOpen(false); onToggleSubmitted(false); }}>
                    Unmark submitted
                  </button>
                )}
                {!isArchived ? (
                  <button type="button" onClick={() => { setMenuOpen(false); onArchive(); }}>
                    Archive
                  </button>
                ) : (
                  <button type="button" onClick={() => { setMenuOpen(false); onUnarchive?.(); }}>
                    Unarchive
                  </button>
                )}
              </div>
            )}
          </div>
        </header>

        <section className="aac-primary-content">
          <MatchRing score={app.aiAnalyzed ? app.matchScore : undefined} tone={statusAccent} />
          <h3 className="aac-role">{app.roleTitle}</h3>
          <p className="aac-company">{app.companyName}</p>
          <ApplicationMeta provider={providerLabel} />
        </section>

        {(app.aiAnalyzed && app.matchScore != null) || totalFields > 0 ? (
          <div className="aac-readiness">
            <ApplicationTimeline
              stageIndex={stage.index}
              stageLabel={timelineLabel}
              accent={statusAccent}
              completedDate={formatTimelineDate(app.updatedAt)}
              isPrepBusy={isPrepBusy}
              isApplying={isApplying}
            />
          </div>
        ) : (
          <div className="aac-readiness aac-readiness--timeline-only">
            <ApplicationTimeline
              stageIndex={stage.index}
              stageLabel={timelineLabel}
              accent={statusAccent}
              completedDate={formatTimelineDate(app.updatedAt)}
              isPrepBusy={isPrepBusy}
              isApplying={isApplying}
            />
          </div>
        )}

        <div className="aac-intelligence">
        {intelligenceSlot ?? (actionAlert ? (
          actionAlert.action === "answer" ? (
            <button
              type="button"
              className={`aac-alert aac-alert--${actionAlert.tone} aac-alert--action`}
              onClick={handleAnswerAlert}
              disabled={isWizardLoading || isAnalyzing}
              aria-label={`${actionAlert.text} — open to answer questions`}
            >
              {isWizardLoading ? "Checking profile…" : actionAlert.text}
              {!isWizardLoading && <span className="aac-alert-arrow" aria-hidden> →</span>}
            </button>
          ) : (
            <p className={`aac-alert aac-alert--${actionAlert.tone}`}>{actionAlert.text}</p>
          )
        ) : quickApplyHint ? <p className="aac-alert aac-alert--info">{quickApplyHint}</p> : totalFields > 0 ? <p className="aac-alert aac-alert--info">{readyFields} of {totalFields} fields ready</p> : null)}
        </div>

        </div>

      </article>

      <SidePanelPortal
        open={drawerOpen}
        onClose={closeDrawer}
        panelClassName="aac-details-panel"
        backdropAriaLabel="Close application details"
        ariaLabelledBy="aac-drawer-title"
      >
        <div className="aa-wizard-panel-inner">
          <header className="aa-wizard-header">
            <div>
              <p className="aa-wizard-eyebrow">{STATUS_LABELS[app.status] || app.status}</p>
              <h2 id="aac-drawer-title">{app.companyName}</h2>
              <p className="aac-drawer-role">{app.roleTitle}</p>
            </div>
            <button type="button" className="aa-wizard-close" aria-label="Close" onClick={closeDrawer}>
              ×
            </button>
          </header>

          <div className="aa-wizard-body aac-drawer-body">
            <section className="aac-drawer-section">
              <h4>Pipeline</h4>
              <ApplicationTimeline
                stageIndex={stage.index}
                stageLabel={timelineLabel}
                accent={statusAccent}
                completedDate={formatTimelineDate(app.updatedAt)}
                isPrepBusy={isPrepBusy}
                isApplying={isApplying}
              />
            </section>

            <section className="aac-drawer-section">
              <h4>Application details</h4>
              <ul className="aac-drawer-stats aac-drawer-details">
                <li>Source · {providerLabel}</li>
                {location && <li>Location · {location}</li>}
                {workplace && <li>Workplace · {workplace}</li>}
                {app.resumeId && <li>Resume · {app.resumeId}</li>}
                {app.resumeFileUsed && (
                  <li>
                    Resume ·{" "}
                    <a
                      href={`/api/backend/application-assistant/autopilot/jobs/${app.id}/resume`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(event) => event.stopPropagation()}
                      style={{ color: "#2ee8c9", textDecoration: "underline" }}
                      title="Open the exact resume PDF submitted for this application"
                    >
                      {app.resumeFileUsed}
                    </a>
                  </li>
                )}
                <li>{isSubmitted ? "Submitted" : "Last updated"} · {updated || "Recently"}</li>
                {app.quickApplyAvailable && <li>Saved application state available</li>}
              </ul>
            </section>

            {app.errors?.length > 0 && (
              <section className="aac-drawer-section">
                <h4>Why</h4>
                <p style={{ margin: 0, fontSize: "12px", lineHeight: 1.5, color: "var(--text-secondary, #cbd5e1)" }}>
                  {formatAppError(app.errors[0])}
                </p>
              </section>
            )}

            <section className="aac-drawer-section">
              <h4>Fields</h4>
              <ul className="aac-drawer-stats">
                {totalFields > 0 && (
                  <li className="aac-drawer-stat aac-drawer-stat--ok">
                    Ready · {readyFields} of {totalFields}
                  </li>
                )}
                {app.reviewCount > 0 && (
                  <li className="aac-drawer-stat aac-drawer-stat--warn">Need review · {app.reviewCount}</li>
                )}
                {app.missingCount > 0 && (
                  <li className="aac-drawer-stat aac-drawer-stat--bad">
                    <button
                      type="button"
                      className="aac-drawer-stat-btn"
                      onClick={(event) => {
                        event.stopPropagation();
                        onAnswerQuestions();
                      }}
                      disabled={isWizardLoading || isAnalyzing}
                    >
                      Missing · {app.missingCount} — answer
                    </button>
                  </li>
                )}
                {app.conflictingCount > 0 && (
                  <li className="aac-drawer-stat aac-drawer-stat--warn">Conflicts · {app.conflictingCount}</li>
                )}
              </ul>

              {app.answers && Object.keys(app.answers).length > 0 && (
                <div style={{ marginTop: "1rem" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.5rem" }}>
                    <h5 style={{ margin: 0, fontSize: "11px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-secondary, #94a3b8)" }}>
                      Submitted Answers ({Object.keys(app.answers).length})
                    </h5>
                  </div>
                  <div style={{ maxHeight: "320px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.5rem", paddingRight: "4px" }}>
                    {Object.entries(app.answers).map(([key, val], idx) => (
                      <div
                        key={idx}
                        style={{
                          padding: "0.6rem 0.75rem",
                          borderRadius: "0.5rem",
                          background: "rgba(255, 255, 255, 0.03)",
                          border: "1px solid rgba(255, 255, 255, 0.07)",
                        }}
                      >
                        <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--text, #e2e8f0)", marginBottom: "0.25rem" }}>
                          {key}
                        </div>
                        <div style={{ fontSize: "11px", fontFamily: "monospace", color: "#2ee8c9", wordBreak: "break-word" }}>
                          {String(val || "—")}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>

            {drawerContentSlot}

            {(actionAlert || errorSlot) && (
              <section className="aac-drawer-section">
                <h4>Blockers</h4>
                {actionAlert && (
                  actionAlert.action === "answer" ? (
                    <button
                      type="button"
                      className={`aac-drawer-blocker aac-drawer-blocker--${actionAlert.tone} aac-drawer-blocker--action`}
                      onClick={handleAnswerAlert}
                      disabled={isWizardLoading || isAnalyzing}
                    >
                      {isWizardLoading ? "Checking profile with Qwen…" : `${actionAlert.text} — click to answer`}
                    </button>
                  ) : (
                    <p className={`aac-drawer-blocker aac-drawer-blocker--${actionAlert.tone}`}>{actionAlert.text}</p>
                  )
                )}
                {errorSlot}
              </section>
            )}

            {reviewBannerSlot && (
              <section className="aac-drawer-section aac-drawer-section--flush">
                {reviewBannerSlot}
              </section>
            )}

            {agentNote && (
              <section className="aac-drawer-section">
                <h4>Agent activity</h4>
                <p className="aac-drawer-activity">{agentNote}</p>
              </section>
            )}

            {prepReportSlot && (
              <section className="aac-drawer-section aac-drawer-section--flush">
                <h4>Preparation report</h4>
                {prepReportSlot}
              </section>
            )}
          </div>

          <footer className="aac-drawer-foot">
            {!isSubmitted && !isBrowserOpen && readiness.canQuickApply && (
              <button type="button" className="aac-drawer-btn" onClick={onOpenInBrowser} disabled={isOpening || isAnalyzing}>
                Quick apply
              </button>
            )}
            {!isBrowserOpen && !readiness.canQuickApply && app.lastPrepFailed && (
              <button type="button" className="aac-drawer-btn" onClick={onResume} disabled={isOpening || isAnalyzing || isPreparing || isActivePrep}>
                Retry prep
              </button>
            )}
            {isBrowserOpen && readiness.canQuickApply && (
              <button type="button" className="aac-drawer-btn" onClick={onOpenInBrowser}>
                Quick apply
              </button>
            )}
            {isBrowserOpen && !readiness.canQuickApply && (
              <button type="button" className="aac-drawer-btn" onClick={onFocusBrowser}>
                Focus browser
              </button>
            )}
            {primary && (
              <button
                type="button"
                className="aac-drawer-btn aac-drawer-btn--primary"
                onClick={(event) => {
                  closeDrawer();
                  handlePrimary(event);
                }}
                disabled={primary.disabled}
              >
                {primary.label} →
              </button>
            )}
          </footer>
        </div>
      </SidePanelPortal>
    </div>
  );
}
