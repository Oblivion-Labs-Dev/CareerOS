"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { QwenLiveFloat, type LiveLogLine } from "@/components/qwen/qwen-live-float";
import { usePrepQueueStatus } from "@/hooks/use-prep-queue-status";
import { ApplicationQueueCard } from "@/components/application-assistant/application-queue-card";
import {
  resolveApplicationReadiness,
  resolveQueueGroupKey,
} from "@/components/application-assistant/application-readiness";
import { ProfileQuestionsWizard, type PendingQuestion } from "@/components/application-assistant/profile-questions-wizard";
import { SidePanelPortal } from "@/components/side-panel-portal";
import {
  isConsentQuestion,
  isFreeTextApplicationQuestion,
  looksLikePhoneCountryOptions,
  normalizeFieldOptions,
} from "@/lib/profile-form-options";
import {
  archiveApplication,
  closeApplicationBrowser,
  getAggregatePendingFields,
  getPendingFields,
  getDashboardStats,
  getQwenAgentStatus,
  getReviewStatus,
  listApplications,
  listProviders,
  markSubmitted,
  openApplicationReview,
  unmarkSubmitted,
  qwenPrepareApplication,
  type PrepQueueStatus,
} from "@/lib/application-assistant-api";

type Application = {
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
  aiAnalyzedAt?: string;
  matchScore?: number;
  updatedAt: string;
  jobId?: string;
  resumeId?: string;
  jobLocation?: string;
  workplaceType?: string;
  currentPage: string;
  errors: { error?: string; type?: string }[];
  skipped?: { field?: string; reason?: string }[];
  prepLog?: Record<string, unknown> | null;
  browserPlan?: { fillActions?: unknown[]; savedAt?: string; actionCount?: number } | null;
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
  wizardPendingCache?: {
    pending?: PendingQuestion[];
    profilePending?: PendingQuestion[];
    applicationPending?: PendingQuestion[];
    profileKeysMissing?: string[];
  };
};

type DashboardStats = {
  statusCounts: Record<string, number>;
  totalApplications: number;
  fieldTotals: { verified: number; missing: number; needsReview: number };
  activePrep: { active?: boolean; applicationId?: string; step?: string } | null;
  scraper?: {
    scraperTotal: number;
    syncedTotal: number;
    pendingSync: number;
    lastScrapedAt?: string;
  };
};

const STATUS_LABELS: Record<string, string> = {
  ready_to_prepare: "Ready to prepare",
  in_progress: "In progress",
  needs_review: "Quick apply",
  blocked: "Blocked",
  ready_for_final_review: "Ready for final review",
  submitted_manually: "Submitted manually",
  archived: "Archived",
};

const STATUS_ACCENT: Record<string, string> = {
  ready_to_prepare: "cyan",
  in_progress: "violet",
  needs_review: "amber",
  blocked: "rose",
  ready_for_final_review: "emerald",
  submitted_manually: "teal",
  archived: "slate",
};

function appIsActivelyPreparing(
  appId: string,
  app: Application,
  prepQueue: PrepQueueStatus | null,
  preparing: Set<string>,
  activePrepIds: Set<string>,
): boolean {
  if (preparing.has(appId)) return true;
  if (activePrepIds.has(appId)) return true;
  if (!prepQueue) return false;
  return (
    prepQueue.activeApplicationIds.includes(appId)
    || prepQueue.queuedApplicationIds.includes(appId)
  );
}

/** Map an application to the queue section that matches its readiness (Quick apply vs retry). */
function resolveQueueGroupKeyForApp(
  app: Application,
  opts: {
    readiness: ReturnType<typeof resolveApplicationReadiness>;
    isPreparing?: boolean;
  },
): string {
  return resolveQueueGroupKey(app, {
    readyForBrowser: opts.readiness.readyForBrowser,
    profileBlocked: opts.readiness.profileBlocked,
    needsAiAnalysis: opts.readiness.needsAiAnalysis,
    canQuickApply: opts.readiness.canQuickApply,
    needsStartPrep: opts.readiness.needsStartPrep,
    isPreparing: opts.isPreparing,
    lastPrepFailed: Boolean(app.lastPrepFailed),
  });
}

const QUEUE_GROUPS = [
  { key: "needs_review", label: "Quick apply" },
  { key: "ready_to_prepare", label: "Start prep" },
  { key: "blocked", label: "Blocked" },
  { key: "ready_for_final_review", label: "Ready for final review" },
  { key: "submitted_manually", label: "Submitted manually" },
  { key: "archived", label: "Archived" },
];

type ReviewSessionStatus = {
  status: "idle" | "opening" | "browser_open" | "ready" | "failed" | "profile_incomplete" | "submitted" | "preparing" | "busy";
  message: string;
  browserOpen: boolean;
  readyForBrowser?: boolean;
  pendingFieldCount?: number;
  elapsedSec?: number;
  updatedAt: number;
};

const REVIEW_STATUS_LABELS: Record<string, string> = {
  opening: "Opening browser…",
  browser_open: "Form open — submit on the job site",
  submitted: "Submitted",
  ready: "Ready to open",
  failed: "Could not open browser",
  profile_incomplete: "Answer profile questions first",
  preparing: "Prep still running",
  busy: "Application busy",
  idle: "",
};

type PrepReportProps = {
  app: Application;
};

function formatAppError(err: Application["errors"][number] | undefined): string {
  if (!err) return "Error occurred";
  if (typeof err === "string") return err;
  if (typeof err.error === "string") return err.error;
  const message = (err as { message?: string }).message;
  if (typeof message === "string") return message;
  try {
    return JSON.stringify(err);
  } catch {
    return "Error occurred";
  }
}

type ProfileGateEntry = { count: number; ready: boolean; loading?: boolean; aiAnalyzed?: boolean };

function resolveProfileGate(app: Application, gate?: ProfileGateEntry) {
  const readiness = resolveApplicationReadiness(app, gate);
  const canOpenBrowser =
    ["needs_review", "in_progress", "blocked"].includes(app.status) &&
    !readiness.profileBlocked &&
    !readiness.gateLoading &&
    !readiness.needsAiAnalysis &&
    readiness.readyForBrowser;
  return { ...readiness, canOpenBrowser };
}

function stripOpeningMessageSuffix(message: string): string {
  return message.replace(/\s*\(\d+s\)\s*$/i, "").replace(/(…|\.\.\.)\s*\(\d+s\)/gi, "$1");
}

export type QuestionsGateHandle = {
  openWizard: () => void;
  loadWithAi: () => Promise<void>;
};

type AppWizardData = {
  pending: PendingQuestion[];
  profilePending: PendingQuestion[];
  applicationPending: PendingQuestion[];
  profileKeysMissing: string[];
};

function applyPendingApiResponse(res: Awaited<ReturnType<typeof getPendingFields>>): AppWizardData {
  const items = (res.pending || []) as PendingQuestion[];
  let profile = (res.profilePending || []) as PendingQuestion[];
  let application = (res.applicationPending || []) as PendingQuestion[];
  if (items.length > 0 && profile.length + application.length === 0) {
    application = items;
  }
  return {
    pending: items,
    profilePending: profile,
    applicationPending: application,
    profileKeysMissing: res.profileKeysMissing || [],
  };
}

function sanitizeWizardQuestion(field: PendingQuestion): PendingQuestion {
  let next = { ...field };
  const options = normalizeFieldOptions(next.options);
  if (looksLikePhoneCountryOptions(options)) {
    next = { ...next, options: [] };
  }
  if (isConsentQuestion(next)) {
    return { ...next, fieldType: "checkbox", options: [] };
  }
  if (isFreeTextApplicationQuestion(next)) {
    return { ...next, fieldType: "text", options: [] };
  }
  return next;
}

function wizardDataFromApplication(app: Application): AppWizardData | null {
  const cache = app.wizardPendingCache;
  if (!cache?.pending?.length) return null;
  const pending = (cache.pending as PendingQuestion[]).map(sanitizeWizardQuestion);
  return {
    pending,
    profilePending: ((cache.profilePending || []) as PendingQuestion[]).map(sanitizeWizardQuestion),
    applicationPending: ((cache.applicationPending || []) as PendingQuestion[]).map(sanitizeWizardQuestion),
    profileKeysMissing: cache.profileKeysMissing || [],
  };
}

function seedWizardDataFromApps(apps: Application[]): Record<string, AppWizardData> {
  const seeded: Record<string, AppWizardData> = {};
  for (const app of apps) {
    const data = wizardDataFromApplication(app);
    if (data?.pending.length) seeded[app.id] = data;
  }
  return seeded;
}

const ProfileQuestionsGate = forwardRef<QuestionsGateHandle, {
  app: Application;
  onSaved: (result: { readyForBrowser: boolean; reprepStarted?: boolean; pendingCount?: number }) => void;
  onPendingChange?: (appId: string, count: number, ready: boolean, loading?: boolean, aiAnalyzed?: boolean) => void;
  onWizardDataLoaded?: (appId: string, data: AppWizardData) => void;
  deferAutoOpen?: boolean;
  hideWizard?: boolean;
  hideBanner?: boolean;
  wizardData?: AppWizardData | null;
  wizardOpen?: boolean;
  onWizardOpenChange?: (open: boolean) => void;
  onWizardLoadError?: (message: string) => void;
  wizardLoading?: boolean;
}>(function ProfileQuestionsGate(
{
  app,
  onSaved,
  onPendingChange,
  onWizardDataLoaded,
  deferAutoOpen = false,
  hideWizard = false,
  hideBanner = false,
  wizardData = null,
  wizardOpen: wizardOpenControlled,
  onWizardOpenChange,
  onWizardLoadError,
  wizardLoading = false,
},
ref,
) {
  const [pending, setPending] = useState<PendingQuestion[]>([]);
  const [profilePending, setProfilePending] = useState<PendingQuestion[]>([]);
  const [applicationPending, setApplicationPending] = useState<PendingQuestion[]>([]);
  const [profileKeysMissing, setProfileKeysMissing] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [internalWizardOpen, setInternalWizardOpen] = useState(false);

  const wizardOpen = wizardOpenControlled ?? internalWizardOpen;
  const setWizardOpen = useCallback((open: boolean) => {
    if (onWizardOpenChange) onWizardOpenChange(open);
    else setInternalWizardOpen(open);
  }, [onWizardOpenChange]);

  const effectivePending = wizardData?.pending ?? pending;
  const effectiveProfilePending = wizardData?.profilePending ?? profilePending;
  const effectiveApplicationPending = wizardData?.applicationPending ?? applicationPending;
  const effectiveProfileKeysMissing = wizardData?.profileKeysMissing ?? profileKeysMissing;

  function applyPendingResponse(res: Awaited<ReturnType<typeof getPendingFields>>) {
    const data = applyPendingApiResponse(res);
    setPending(data.pending);
    setProfilePending(data.profilePending);
    setApplicationPending(data.applicationPending);
    setProfileKeysMissing(data.profileKeysMissing);
    return data.pending;
  }

  const loadPending = useCallback(async (useAi: boolean) => {
    if (!useAi) {
      const cached = wizardData ?? wizardDataFromApplication(app);
      if (cached?.pending.length) {
        setPending(cached.pending);
        setProfilePending(cached.profilePending);
        setApplicationPending(cached.applicationPending);
        setProfileKeysMissing(cached.profileKeysMissing);
        onWizardDataLoaded?.(app.id, cached);
        onPendingChange?.(app.id, cached.pending.length, false, false, true);
        return cached;
      }
    }
    setLoading(true);
    onPendingChange?.(app.id, app.missingCount ?? 0, false, useAi);
    try {
      const res = await getPendingFields(app.id, { useAi });
      const data = applyPendingApiResponse(res);
      applyPendingResponse(res);
      onWizardDataLoaded?.(app.id, data);
      onPendingChange?.(app.id, data.pending.length, Boolean(res.readyForBrowser), false, useAi || Boolean(res.aiAnalyzed));
      return data;
    } catch (err) {
      setPending([]);
      setProfilePending([]);
      setApplicationPending([]);
      setProfileKeysMissing([]);
      onPendingChange?.(app.id, app.missingCount ?? 0, (app.missingCount ?? 0) === 0, false, false);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [app, onPendingChange, onWizardDataLoaded, wizardData]);

  const loadWithAi = useCallback(async () => {
    await loadPending(!app.aiAnalyzed);
  }, [app.aiAnalyzed, loadPending]);

  const openWizardWithLoad = useCallback(async () => {
    setWizardOpen(true);
    if (effectivePending.length > 0) return;
    const cached = wizardData ?? wizardDataFromApplication(app);
    if (cached?.pending.length) {
      setPending(cached.pending);
      setProfilePending(cached.profilePending);
      setApplicationPending(cached.applicationPending);
      setProfileKeysMissing(cached.profileKeysMissing);
      onWizardDataLoaded?.(app.id, cached);
      return;
    }
    const useAi = !app.aiAnalyzed;
    try {
      await loadPending(useAi);
    } catch (err) {
      setWizardOpen(false);
      onWizardLoadError?.(err instanceof Error ? err.message : "Could not load questions");
    }
  }, [
    app,
    effectivePending.length,
    loadPending,
    onWizardDataLoaded,
    onWizardLoadError,
    setWizardOpen,
    wizardData,
  ]);

  useImperativeHandle(ref, () => ({
    openWizard: () => {
      void openWizardWithLoad();
    },
    loadWithAi,
  }));

  if (hideWizard) return null;

  const profileCount = effectiveProfilePending.length;
  const applicationCount = effectiveApplicationPending.length;

  const wizard = (
    <ProfileQuestionsWizard
      open={wizardOpen}
      onClose={() => setWizardOpen(false)}
      layout="panel"
      loading={wizardLoading || loading}
      loadingMessage={app.aiAnalyzed || wizardData ? "Loading saved questions…" : "Checking your profile with Qwen…"}
      appId={app.id}
      companyName={app.companyName}
      roleTitle={app.roleTitle}
      pending={effectivePending}
      profilePending={effectiveProfilePending}
      applicationPending={effectiveApplicationPending}
      profileKeysMissing={effectiveProfileKeysMissing}
        onComplete={async (result) => {
        try {
          const refreshed = await getPendingFields(app.id, { useAi: false });
          const data = applyPendingApiResponse(refreshed);
          applyPendingResponse(refreshed);
          onWizardDataLoaded?.(app.id, data);
          onPendingChange?.(
            app.id,
            data.pending.length,
            Boolean(refreshed.readyForBrowser),
            false,
            Boolean(refreshed.aiAnalyzed),
          );
        } catch {
          onPendingChange?.(
            app.id,
            result.pendingCount ?? 0,
            result.readyForBrowser,
            false,
            true,
          );
        }
        onSaved({
          readyForBrowser: result.readyForBrowser,
          reprepStarted: result.reprepStarted,
          pendingCount: result.pendingCount,
        });
      }}
    />
  );

  return (
    <>
      {!hideBanner && !loading && effectivePending.length > 0 && (
        <div className="aa-profile-gate">
          <div className="aa-profile-gate-copy">
            <strong>{effectivePending.length} question{effectivePending.length === 1 ? "" : "s"} before you can open the browser</strong>
            <p className="muted">
              {profileCount > 0 && (
                <>
                  {profileCount} saved to your profile
                  {applicationCount > 0 ? " · " : ""}
                </>
              )}
              {applicationCount > 0 && `${applicationCount} for this application`}
              {profileCount === 0 && applicationCount === 0 ? "Answer them in the wizard to continue." : "."}
            </p>
          </div>
          <button type="button" className="btn-primary btn-sm" onClick={() => void openWizardWithLoad()}>
            Answer {effectivePending.length} question{effectivePending.length === 1 ? "" : "s"}
          </button>
        </div>
      )}
      {wizard}
    </>
  );
});

const UnifiedQuestionsGate = forwardRef<QuestionsGateHandle, {
  appIds: string[];
  applicationCount: number;
  onComplete: (result: { readyForBrowser: boolean; reprepStarted?: boolean }) => void;
  onAppsAnalyzed?: (apps: { appId: string; pendingCount: number; ready: boolean }[]) => void;
}>(function UnifiedQuestionsGate(
{
  appIds,
  applicationCount,
  onComplete,
  onAppsAnalyzed,
},
ref,
) {
  const [pending, setPending] = useState<PendingQuestion[]>([]);
  const [profilePending, setProfilePending] = useState<PendingQuestion[]>([]);
  const [applicationPending, setApplicationPending] = useState<PendingQuestion[]>([]);
  const [profileKeysMissing, setProfileKeysMissing] = useState<string[]>([]);
  const [rawOccurrenceCount, setRawOccurrenceCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const loadWithAi = useCallback(async () => {
    if (!appIds.length) return;
    setLoading(true);
    try {
      const res = await getAggregatePendingFields(appIds, { useAi: true });
      setPending((res.pending || []) as PendingQuestion[]);
      setProfilePending((res.profilePending || []) as PendingQuestion[]);
      setApplicationPending((res.applicationPending || []) as PendingQuestion[]);
      setProfileKeysMissing(res.profileKeysMissing || []);
      setRawOccurrenceCount(res.rawOccurrenceCount || 0);
      setLoaded(true);
      if (res.applications?.length) {
        onAppsAnalyzed?.(
          res.applications.map((app) => ({
            appId: app.appId,
            pendingCount: app.pendingCount,
            ready: Boolean(app.readyForBrowser),
          })),
        );
      }
    } catch (err) {
      setPending([]);
      setProfilePending([]);
      setApplicationPending([]);
      setProfileKeysMissing([]);
      setLoaded(false);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [appIds.join(","), onAppsAnalyzed]);

  useImperativeHandle(ref, () => ({
    openWizard: () => setWizardOpen(true),
    loadWithAi,
  }));

  if (loading) {
    return (
      <div className="aa-profile-gate-banner" role="status">
        Qwen is interpreting and deduplicating questions across {applicationCount} applications…
      </div>
    );
  }
  if (!loaded || !pending.length) return null;

  return (
    <>
      <div className="aa-profile-gate-banner aa-profile-gate-banner--action" role="status">
        <div>
          <strong>{applicationCount} applications</strong>
          {" · "}
          <strong>{rawOccurrenceCount} raw question{rawOccurrenceCount === 1 ? "" : "s"}</strong>
          {" → "}
          <strong>{pending.length} unique question{pending.length === 1 ? "" : "s"}</strong>
          {" after AI normalization."}
        </div>
        <button type="button" className="btn-primary btn-sm" onClick={() => setWizardOpen(true)}>
          Answer {pending.length} question{pending.length === 1 ? "" : "s"} once
        </button>
      </div>

      <ProfileQuestionsWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        layout="panel"
        mode="unified"
        pending={pending}
        profilePending={profilePending}
        applicationPending={applicationPending}
        profileKeysMissing={profileKeysMissing}
        applicationCount={applicationCount}
        rawOccurrenceCount={rawOccurrenceCount}
        onComplete={async (result) => {
          try {
            const refreshed = await getAggregatePendingFields(appIds, { useAi: true });
            setPending((refreshed.pending || []) as PendingQuestion[]);
            setProfilePending((refreshed.profilePending || []) as PendingQuestion[]);
            setApplicationPending((refreshed.applicationPending || []) as PendingQuestion[]);
            setProfileKeysMissing(refreshed.profileKeysMissing || []);
            setRawOccurrenceCount(refreshed.rawOccurrenceCount || 0);
          } catch {
            /* keep prior state */
          }
          onComplete(result);
        }}
      />
    </>
  );
});

function PrepReportPanel({ app, embedded = false }: PrepReportProps & { embedded?: boolean }) {
  const [open, setOpen] = useState(false);
  const prepLog = app.prepLog;
  const prepErrors = app.errors?.length ? app.errors : (prepLog?.errors as { error?: string; type?: string }[] | undefined) || [];
  const prepSkipped = app.skipped?.length ? app.skipped : (prepLog?.skipped as { field?: string; reason?: string }[] | undefined) || [];
  const unknownFields = (prepLog?.unknownFields as { label?: string; normalizedKey?: string; fieldType?: string }[] | undefined)
    || (app.fields || []).filter((f) => f.classification === "unknown").map((f) => ({
      label: f.label,
      normalizedKey: f.normalizedKey,
      fieldType: f.fieldType,
    }));
  const stoppedReason = app.stoppedReason || (prepLog?.stoppedReason as string | undefined) || "";
  const hasData = prepErrors.length > 0 || prepSkipped.length > 0 || unknownFields.length > 0 || stoppedReason || prepLog;

  if (!hasData && app.missingCount === 0) return null;

  const filledCount = String(prepLog?.filledCount ?? app.verifiedCount ?? 0);
  const summaryParts = [
    `Filled ${filledCount}`,
    `Missing ${unknownFields.length || app.missingCount}`,
    prepErrors.length ? `Errors ${prepErrors.length}` : null,
  ].filter(Boolean);

  const body = (
    <div className="aa-prep-report-body">
      <p className="muted aa-prep-report-hint">
        Complete the application in the browser window — this panel only shows what Qwen could not fill or parse.
      </p>
      {(prepLog || app.missingCount > 0) && (
        <div className="aa-prep-log-summary">
          {prepLog ? (
            <>
              <span>Filled: {filledCount}</span>
              <span>Unrecognized: {String(prepLog.unknownCount ?? unknownFields.length)}</span>
              <span>Skipped: {String(prepLog.skippedCount ?? prepSkipped.length)}</span>
              <span>Errors: {String(prepLog.errorCount ?? prepErrors.length)}</span>
            </>
          ) : (
            <span>Missing: {app.missingCount}</span>
          )}
          {stoppedReason ? <span>Stop reason: {stoppedReason}</span> : null}
        </div>
      )}
      {prepErrors.length > 0 && (
        <div className="aa-prep-log-block">
          <h5>Errors</h5>
          <ul>{prepErrors.map((e, i) => <li key={i}>{formatAppError(e)}</li>)}</ul>
        </div>
      )}
      {unknownFields.length > 0 && (
        <div className="aa-prep-log-block">
          <h5>Missing / unrecognized fields</h5>
          <ul>
            {unknownFields.slice(0, 25).map((f, i) => (
              <li key={i}>
                <strong>{f.label || f.normalizedKey || "Unknown field"}</strong>
                {f.fieldType ? <> · type: {f.fieldType}</> : null}
              </li>
            ))}
          </ul>
          {unknownFields.length > 25 && <p className="muted">+{unknownFields.length - 25} more</p>}
        </div>
      )}
      {prepSkipped.length > 0 && (
        <div className="aa-prep-log-block">
          <h5>Skipped fields</h5>
          <ul>{prepSkipped.slice(0, 15).map((s, i) => <li key={i}><strong>{s.field || "Field"}</strong> — {s.reason || "skipped"}</li>)}</ul>
        </div>
      )}
    </div>
  );

  if (embedded) {
    return <div className="aa-prep-report aa-prep-report--embedded">{body}</div>;
  }

  return (
    <div className={`aa-prep-report${open ? " aa-prep-report--open" : ""}`}>
      <button
        type="button"
        className="aa-prep-report-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="aa-prep-report-toggle-main">
          <strong>Prep report</strong>
          <span className="muted aa-prep-report-toggle-summary">{summaryParts.join(" · ")}</span>
        </span>
        <span className="aa-prep-report-chevron" aria-hidden>{open ? "▾" : "▸"}</span>
      </button>
      {open && body}
    </div>
  );
}

function ReviewStatusBanner({
  session,
  openingElapsedSec,
  onBrowserClosed,
  onAnswerQuestions,
  closingBrowser,
  answeringQuestions,
}: {
  session: ReviewSessionStatus | undefined;
  openingElapsedSec?: number;
  onBrowserClosed?: () => void;
  onAnswerQuestions?: () => void;
  closingBrowser?: boolean;
  answeringQuestions?: boolean;
}) {
  if (!session || session.status === "idle" || session.status === "ready") return null;

  const elapsed = openingElapsedSec ?? session.elapsedSec ?? 0;
  const stuck = session.status === "opening" && elapsed > 90;
  const openingMessage =
    session.status === "opening"
      ? `${stripOpeningMessageSuffix(session.message)} (${elapsed}s)`
      : session.message;

  return (
    <div
      className={`aa-review-status aa-review-status--${session.status}${stuck ? " aa-review-status--stuck" : ""}`}
      role="status"
    >
      <span className="aa-review-status-dot" aria-hidden />
      <div>
        <strong>{REVIEW_STATUS_LABELS[session.status] || session.status}</strong>
        <p>{openingMessage}{stuck ? " This is taking longer than usual — check for a browser window behind other apps." : ""}</p>
        {session.status === "profile_incomplete" && onAnswerQuestions && (
          <button
            type="button"
            className="btn-primary btn-sm aa-review-dismiss"
            onClick={onAnswerQuestions}
            disabled={answeringQuestions}
          >
            {answeringQuestions
              ? "Loading questions…"
              : `Answer ${session.pendingFieldCount ?? "profile"} question${session.pendingFieldCount === 1 ? "" : "s"}`}
          </button>
        )}
        {session.status === "browser_open" && onBrowserClosed && (
          <button
            type="button"
            className="btn-secondary btn-sm aa-review-dismiss"
            onClick={onBrowserClosed}
            disabled={closingBrowser}
          >
            {closingBrowser ? "Clearing…" : "I closed the browser"}
          </button>
        )}
      </div>
    </div>
  );
}

function dispatchQwenContext(appId: string, company?: string, role?: string) {
  window.dispatchEvent(
    new CustomEvent("qwen-app-context", { detail: { applicationId: appId, companyName: company, roleTitle: role } }),
  );
}

function StatusBarChart({ counts, total }: { counts: Record<string, number>; total: number }) {
  const entries = QUEUE_GROUPS.map((g) => ({ label: g.label, key: g.key, value: counts[g.key] || 0 })).filter(
    (e) => e.value > 0,
  );
  if (!entries.length) {
    return <p className="muted aa-chart-empty">No applications yet.</p>;
  }
  const max = Math.max(...entries.map((e) => e.value), 1);
  return (
    <div className="aa-bar-chart" aria-label="Applications by status">
      {entries.map((entry) => (
        <div key={entry.key} className="aa-bar-row">
          <span className="aa-bar-label">{entry.label}</span>
          <div className="aa-bar-track">
            <span
              className={`aa-bar-fill aa-bar-fill--${entry.key}`}
              style={{ width: `${Math.max(8, (entry.value / max) * 100)}%` }}
            />
          </div>
          <strong className="aa-bar-value">{entry.value}</strong>
        </div>
      ))}
      <p className="aa-chart-footnote">{total} total applications</p>
    </div>
  );
}

function FieldDonutChart({ verified, missing, needsReview }: { verified: number; missing: number; needsReview: number }) {
  const total = verified + missing + needsReview || 1;
  const vPct = (verified / total) * 100;
  const mPct = (missing / total) * 100;
  const rPct = (needsReview / total) * 100;
  const gradient = `conic-gradient(
    var(--success) 0% ${vPct}%,
    var(--warning) ${vPct}% ${vPct + rPct}%,
    var(--muted) ${vPct + rPct}% 100%
  )`;
  return (
    <div className="aa-donut-wrap">
      <div className="aa-donut" style={{ background: gradient }} aria-hidden>
        <div className="aa-donut-hole">
          <strong>{Math.round((verified / total) * 100)}%</strong>
          <span>filled</span>
        </div>
      </div>
      <ul className="aa-donut-legend">
        <li><span className="aa-legend-dot aa-legend-dot--verified" /> Verified {verified}</li>
        <li><span className="aa-legend-dot aa-legend-dot--review" /> Review {needsReview}</li>
        <li><span className="aa-legend-dot aa-legend-dot--missing" /> Missing {missing}</li>
      </ul>
    </div>
  );
}

const AA_APPS_CACHE_KEY = "careeros-aa-applications-v1";
const AA_APPS_FETCH_TIMEOUT_MS = 45_000;
const AA_APPS_MAX_ATTEMPTS = 3;

function slimApplicationForCache(app: Application): Application {
  const { fields: _fields, browserPlan: _plan, prepLog: _prepLog, ...rest } = app;
  return rest as Application;
}

function readApplicationsCache(): Application[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(AA_APPS_CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as Application[]) : [];
  } catch {
    return [];
  }
}

function writeApplicationsCache(apps: Application[]) {
  try {
    sessionStorage.setItem(
      AA_APPS_CACHE_KEY,
      JSON.stringify(apps.map(slimApplicationForCache)),
    );
  } catch {
    /* quota / private mode */
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function ApplicationQueueSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="aa-queue-grid aa-queue-grid--skeleton" aria-hidden>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="aa-queue-card-skeleton" />
      ))}
    </div>
  );
}

export function ApplicationAssistantDashboard() {
  const searchParams = useSearchParams();
  const focusAppId = searchParams.get("app");
  const [highlightAppId, setHighlightAppId] = useState<string | null>(null);
  const focusScrollDoneRef = useRef<string | null>(null);

  const [applications, setApplications] = useState<Application[]>([]);
  const [applicationsLoading, setApplicationsLoading] = useState(true);
  const [applicationsLoadError, setApplicationsLoadError] = useState("");
  const [applicationsHydrated, setApplicationsHydrated] = useState(false);
  const [providers, setProviders] = useState<{ name: string; supported: boolean }[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);

  const [preparing, setPreparing] = useState<Set<string>>(new Set());
  const [activePrepIds, setActivePrepIds] = useState<Set<string>>(new Set());
  const { status: prepQueue, refresh: refreshPrepQueue } = usePrepQueueStatus();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [openingReview, setOpeningReview] = useState<string | null>(null);
  const [openingTick, setOpeningTick] = useState(0);
  const openingStartedAtRef = useRef<Record<string, number>>({});
  const [prepTick, setPrepTick] = useState(0);
  const prepStartedAtRef = useRef<Record<string, number>>({});
  const [closingBrowser, setClosingBrowser] = useState<string | null>(null);
  const [reviewSessions, setReviewSessions] = useState<Record<string, ReviewSessionStatus>>({});
  const [profileGate, setProfileGate] = useState<Record<string, ProfileGateEntry>>({});
  const [bootstrapping, setBootstrapping] = useState(true);
  const unifiedGateRef = useRef<QuestionsGateHandle>(null);
  const gateRefs = useRef<Record<string, QuestionsGateHandle | null>>({});
  const queueAnalyzeRef = useRef<HTMLDivElement>(null);
  const autoFieldAnalysisRef = useRef(new Set<string>());
  const autoFieldAnalysisDoneRef = useRef(new Set<string>());
  const [wizardDataByApp, setWizardDataByApp] = useState<Record<string, AppWizardData>>({});
  const [wizardOpenAppId, setWizardOpenAppId] = useState<string | null>(null);
  const [wizardLoadingAppId, setWizardLoadingAppId] = useState<string | null>(null);
  const [liveFloatLines, setLiveFloatLines] = useState<LiveLogLine[]>([]);
  const [liveFloatHold, setLiveFloatHold] = useState(false);
  const [missingOverview, setMissingOverview] = useState<{
    open: boolean;
    loading: boolean;
    data: AppWizardData | null;
    appIds: string[];
    singleApp: Application | null;
    rawOccurrenceCount: number;
  }>({
    open: false,
    loading: false,
    data: null,
    appIds: [],
    singleApp: null,
    rawOccurrenceCount: 0,
  });

  const pushLiveFloat = useCallback((summary: string, type = "analyze_progress") => {
    setLiveFloatLines((prev) => [
      ...prev,
      {
        id: `local_${Date.now()}_${prev.length}`,
        timestamp: new Date().toISOString(),
        type,
        summary,
        success: true,
        local: true,
      },
    ]);
  }, []);

  const markOpeningStarted = useCallback((appId: string, session?: ReviewSessionStatus) => {
    if (!openingStartedAtRef.current[appId]) {
      openingStartedAtRef.current[appId] = session?.updatedAt ?? Date.now();
    }
  }, []);

  const clearOpeningStarted = useCallback((appId: string) => {
    delete openingStartedAtRef.current[appId];
  }, []);

  const getOpeningElapsed = useCallback((appId: string, session?: ReviewSessionStatus) => {
    markOpeningStarted(appId, session);
    const startedAt = openingStartedAtRef.current[appId];
    if (!startedAt) return session?.elapsedSec ?? 0;
    const local = Math.floor((Date.now() - startedAt) / 1000);
    return Math.max(session?.elapsedSec ?? 0, local);
  }, [markOpeningStarted]);

  const hasOpeningSession =
    openingReview != null ||
    Object.values(reviewSessions).some((session) => session.status === "opening");

  const handlePendingChange = useCallback((
    appId: string,
    count: number,
    ready: boolean,
    loading = false,
    aiAnalyzed?: boolean,
  ) => {
    setProfileGate((prev) => ({
      ...prev,
      [appId]: {
        count,
        ready,
        loading,
        aiAnalyzed: aiAnalyzed ?? prev[appId]?.aiAnalyzed ?? false,
      },
    }));
    if (!loading && !ready && count > 0) {
      setReviewSessions((prev) => ({
        ...prev,
        [appId]: {
          status: "profile_incomplete",
          message: `Answer ${count} profile question(s) using the wizard before opening the browser.`,
          browserOpen: false,
          readyForBrowser: false,
          pendingFieldCount: count,
          updatedAt: Date.now(),
        },
      }));
    }
  }, []);

  const prefetchWizardQuestions = useCallback(async (appId: string) => {
    if (autoFieldAnalysisDoneRef.current.has(appId)) return;
    autoFieldAnalysisDoneRef.current.add(appId);
    try {
      const res = await getPendingFields(appId, { useAi: false });
      const data = applyPendingApiResponse(res);
      setWizardDataByApp((prev) => ({ ...prev, [appId]: data }));
      handlePendingChange(appId, data.pending.length, Boolean(res.readyForBrowser), false, true);
    } catch {
      autoFieldAnalysisDoneRef.current.delete(appId);
    }
  }, [handlePendingChange]);

  const runPostPrepFieldAnalysis = useCallback(async (app: Application) => {
    if (app.aiAnalyzed || autoFieldAnalysisDoneRef.current.has(app.id) || autoFieldAnalysisRef.current.has(app.id)) {
      if (app.aiAnalyzed) {
        void prefetchWizardQuestions(app.id);
      }
      return;
    }
    autoFieldAnalysisRef.current.add(app.id);
    handlePendingChange(app.id, app.missingCount ?? 0, false, true);
    try {
      const res = await getPendingFields(app.id, { useAi: true });
      const data = applyPendingApiResponse(res);
      setWizardDataByApp((prev) => ({ ...prev, [app.id]: data }));
      handlePendingChange(app.id, data.pending.length, Boolean(res.readyForBrowser), false, true);
      autoFieldAnalysisDoneRef.current.add(app.id);
    } catch {
      handlePendingChange(app.id, app.missingCount ?? 0, false, false, false);
    } finally {
      autoFieldAnalysisRef.current.delete(app.id);
    }
  }, [handlePendingChange, prefetchWizardQuestions]);

  const loadStats = useCallback(async () => {
    try {
      const res = await getDashboardStats();
      setStats({
        statusCounts: res.statusCounts,
        totalApplications: res.totalApplications,
        fieldTotals: res.fieldTotals,
        activePrep: res.activePrep,
        scraper: res.scraper,
      });
      if (res.activePrep?.active && res.activePrep.applicationId) {
        setActivePrepIds((prev) => new Set(prev).add(String(res.activePrep!.applicationId)));
      }
    } catch {
      /* backend may be offline */
    }
  }, []);

  const loadApplications = useCallback(async (externalSignal?: AbortSignal) => {
    setApplicationsLoading(true);
    setApplicationsLoadError("");
    try {
      let lastError: unknown;
      for (let attempt = 0; attempt < AA_APPS_MAX_ATTEMPTS; attempt += 1) {
        if (externalSignal?.aborted) {
          throw new DOMException("Aborted", "AbortError");
        }
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), AA_APPS_FETCH_TIMEOUT_MS);
        const abortExternal = () => controller.abort();
        externalSignal?.addEventListener("abort", abortExternal, { once: true });
        try {
          const res = await listApplications({ signal: controller.signal });
          window.clearTimeout(timeout);
          externalSignal?.removeEventListener("abort", abortExternal);
          const apps = Array.isArray(res.applications) ? (res.applications as Application[]) : [];
          setApplications(apps);
          writeApplicationsCache(apps);
          setWizardDataByApp((prev) => ({ ...seedWizardDataFromApps(apps), ...prev }));
          setProfileGate((prev) => {
            const next = { ...prev };
            for (const app of apps) {
              if (app.status !== "needs_review" && app.status !== "blocked") continue;
              const existing = next[app.id];
              if (existing?.loading) continue;
              const aiAnalyzed = Boolean(app.aiAnalyzed || existing?.aiAnalyzed);
              if (aiAnalyzed) {
                next[app.id] = {
                  count: app.pendingFieldCount ?? existing?.count ?? app.missingCount ?? 0,
                  ready: app.readyForBrowser ?? existing?.ready ?? (app.missingCount ?? 0) === 0,
                  loading: false,
                  aiAnalyzed: true,
                };
                continue;
              }
              next[app.id] = {
                count: app.missingCount ?? existing?.count ?? 0,
                ready: (app.missingCount ?? 0) === 0,
                loading: false,
                aiAnalyzed: false,
              };
            }
            return next;
          });
          const analyzed = apps.filter(
            (app) =>
              app.aiAnalyzed &&
              (app.pendingFieldCount ?? 0) > 0 &&
              ["needs_review", "in_progress", "blocked"].includes(app.status) &&
              !wizardDataFromApplication(app),
          );
          if (analyzed.length) {
            void Promise.all(
              analyzed.map(async (app) => {
                try {
                  const pendingRes = await getPendingFields(app.id, { useAi: false });
                  const data = applyPendingApiResponse(pendingRes);
                  if (data.pending.length) {
                    setWizardDataByApp((prev) => ({ ...prev, [app.id]: data }));
                  }
                } catch {
                  /* optional prefetch */
                }
              }),
            );
          }
          return;
        } catch (err) {
          window.clearTimeout(timeout);
          externalSignal?.removeEventListener("abort", abortExternal);
          lastError = err;
          const aborted =
            (err instanceof DOMException && err.name === "AbortError")
            || (err instanceof Error && err.name === "AbortError");
          if (aborted || externalSignal?.aborted) {
            throw err;
          }
          if (attempt < AA_APPS_MAX_ATTEMPTS - 1) {
            await sleep(800 * (attempt + 1));
          }
        }
      }
      throw lastError instanceof Error ? lastError : new Error("Could not load applications");
    } catch (err) {
      const aborted =
        (err instanceof DOMException && err.name === "AbortError")
        || (err instanceof Error && err.name === "AbortError");
      if (aborted) {
        return;
      }
      const message =
        err instanceof Error && err.name === "AbortError"
          ? "Loading applications timed out — the API may be starting up. Try Refresh."
          : err instanceof Error
            ? err.message
            : "Could not load applications";
      setApplicationsLoadError(message);
    } finally {
      setApplicationsLoading(false);
    }
  }, []);

  useEffect(() => {
    for (const app of applications) {
      const gate = profileGate[app.id];
      const { needsAiAnalysis } = resolveProfileGate(app, gate);
      if (
        needsAiAnalysis &&
        ["needs_review", "in_progress", "blocked"].includes(app.status)
      ) {
        void runPostPrepFieldAnalysis(app);
      }
    }
  }, [applications, profileGate, runPostPrepFieldAnalysis]);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadApplications(), loadStats()]);
  }, [loadApplications, loadStats]);

  useEffect(() => {
    const onPrepStarted = () => {
      void refreshAll();
    };
    window.addEventListener("qwen-prep-started", onPrepStarted);
    return () => window.removeEventListener("qwen-prep-started", onPrepStarted);
  }, [refreshAll]);

  useEffect(() => {
    if (focusAppId) return;
    const hash = window.location.hash;
    if (hash === "#application-queue") {
      queueAnalyzeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [focusAppId, bootstrapping]);

  useEffect(() => {
    const cached = readApplicationsCache();
    if (cached.length) {
      setApplications(cached);
    }
    setApplicationsHydrated(true);
  }, []);

  useEffect(() => {
    if (!applicationsHydrated) return undefined;
    const controller = new AbortController();
    void (async () => {
      await loadApplications(controller.signal);
      setBootstrapping(false);
    })();
    void loadStats();
    listProviders().then((r) => setProviders(r.providers)).catch(() => {});
    return () => {
      controller.abort();
    };
  }, [applicationsHydrated, loadApplications, loadStats]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (applicationsLoading) return;
      if (applications.length > 0 && !applicationsLoadError) return;
      void loadApplications();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [applications.length, applicationsLoadError, applicationsLoading, loadApplications]);

  const liveMode = Boolean(activePrepIds.size || stats?.activePrep?.active || openingReview);

  const activeReviewAppIds = useMemo(() => {
    const ids = new Set<string>();
    if (openingReview) ids.add(openingReview);
    for (const [id, session] of Object.entries(reviewSessions)) {
      if (session.status === "opening" || session.browserOpen || session.status === "submitted") {
        ids.add(id);
      }
    }
    return [...ids];
  }, [openingReview, reviewSessions]);

  const pollReviewStatuses = useCallback(async () => {
    if (!activeReviewAppIds.length) return;

    const updates: Record<string, ReviewSessionStatus> = {};
    await Promise.all(
      activeReviewAppIds.map(async (appId) => {
        try {
          const res = await getReviewStatus(appId);
          updates[appId] = {
            status: res.status === "not_found" ? "failed" : res.status,
            message: res.message,
            browserOpen: res.browserOpen,
            readyForBrowser: res.readyForBrowser,
            pendingFieldCount: res.pendingFieldCount,
            elapsedSec: res.elapsedSec,
            updatedAt: Date.now(),
          };
        } catch {
          /* ignore */
        }
      }),
    );
    if (Object.keys(updates).length) {
      let submissionDetected = false;
      let sessionEnded = false;
      setReviewSessions((prev) => {
        const merged = { ...prev, ...updates };
        for (const [appId, session] of Object.entries(updates)) {
          if (session.status === "opening") {
            markOpeningStarted(appId, session);
          } else if (session.status === "browser_open" || session.status === "failed") {
            clearOpeningStarted(appId);
          } else if (session.status === "ready") {
            clearOpeningStarted(appId);
            sessionEnded = true;
          } else if (session.status === "submitted") {
            submissionDetected = true;
            clearOpeningStarted(appId);
          }
          if (openingReview === appId) {
            if (session.status === "browser_open") {
              setOpeningReview(null);
              clearOpeningStarted(appId);
              setMessage("Browser opened — submit on the job site and CareerOS will mark it submitted automatically.");
            } else if (session.status === "ready") {
              setOpeningReview(null);
              clearOpeningStarted(appId);
            } else if (session.status === "failed" || session.status === "profile_incomplete") {
              setOpeningReview(null);
              clearOpeningStarted(appId);
              if (session.status === "failed") {
                setError(session.message || "Could not open the application form.");
              }
            } else if (session.status === "submitted") {
              setOpeningReview(null);
              clearOpeningStarted(appId);
            }
          }
        }
        return merged;
      });
      if (submissionDetected) {
        void loadApplications();
        void loadStats();
        setMessage("Application submitted on the job site — marked automatically in CareerOS.");
        window.dispatchEvent(new CustomEvent("careeros-application-submitted"));
        window.dispatchEvent(new CustomEvent("careeros-job-counts-changed"));
      } else if (sessionEnded) {
        void loadApplications();
      }
    }
  }, [activeReviewAppIds, openingReview, clearOpeningStarted, markOpeningStarted, loadApplications, loadStats]);

  useEffect(() => {
    if (!activeReviewAppIds.length) return;
    void pollReviewStatuses();
    const interval = setInterval(() => void pollReviewStatuses(), hasOpeningSession ? 1000 : 2500);
    return () => clearInterval(interval);
  }, [pollReviewStatuses, activeReviewAppIds.join(","), hasOpeningSession]);

  useEffect(() => {
    if (!hasOpeningSession) return;
    const id = setInterval(() => setOpeningTick((tick) => tick + 1), 1000);
    return () => clearInterval(id);
  }, [hasOpeningSession]);

  const anyPrepActive = useMemo(
    () => applications.some((app) => appIsActivelyPreparing(app.id, app, prepQueue, preparing, activePrepIds)),
    [applications, prepQueue, preparing, activePrepIds],
  );

  useEffect(() => {
    if (!anyPrepActive) return undefined;
    const id = setInterval(() => setPrepTick((value) => value + 1), 1000);
    return () => clearInterval(id);
  }, [anyPrepActive]);

  const getPrepElapsed = useCallback((appId: string) => {
    void prepTick;
    const started = prepStartedAtRef.current[appId];
    return started ? Math.floor((Date.now() - started) / 1000) : 0;
  }, [prepTick]);

  useEffect(() => {
    const inProgress = applications.filter((app) => app.status === "in_progress").map((app) => app.id);
    if (!inProgress.length) return undefined;
    const interval = setInterval(async () => {
      let changed = false;
      for (const appId of inProgress) {
        try {
          const status = await getQwenAgentStatus(appId);
          const runStatus = status.run?.status;
          if (runStatus === "completed" || runStatus === "failed") {
            changed = true;
          }
        } catch {
          /* ignore */
        }
      }
      if (changed) {
        void loadApplications();
        void loadStats();
        void refreshPrepQueue();
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [applications, loadApplications, loadStats, refreshPrepQueue]);

  useEffect(() => {
    if (!prepQueue) return;
    const queued = new Set([
      ...prepQueue.activeApplicationIds,
      ...prepQueue.queuedApplicationIds,
    ]);
    setActivePrepIds(queued);
    const now = Date.now();
    for (const appId of queued) {
      prepStartedAtRef.current[appId] = prepStartedAtRef.current[appId] ?? now;
    }
    const openIds = prepQueue.openBrowserApplicationIds ?? [];
    if (openIds.length === 0) return;
    setReviewSessions((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const appId of openIds) {
        if (next[appId]?.status === "browser_open") continue;
        changed = true;
        next[appId] = {
          status: "browser_open",
          message: "Application form is open in Chrome from prep.",
          browserOpen: true,
          updatedAt: Date.now(),
        };
      }
      return changed ? next : prev;
    });
  }, [prepQueue]);

  useEffect(() => {
    if (!activePrepIds.size) return;
    const interval = setInterval(async () => {
      let changed = false;
      for (const appId of activePrepIds) {
        try {
          const status = await getQwenAgentStatus(appId);
          const runStatus = status.run?.status;
          if (runStatus === "completed" || runStatus === "failed") {
            changed = true;
            setActivePrepIds((prev) => {
              const next = new Set(prev);
              next.delete(appId);
              return next;
            });
            delete prepStartedAtRef.current[appId];
            if (status.run?.success) {
              setMessage(`Qwen completed: ${status.run.verifiedCount ?? 0} verified fields filled.`);
              void prefetchWizardQuestions(appId);
            } else {
              setError(status.run?.analysis || status.run?.stoppedReason || "Qwen could not complete prep — see chat below.");
            }
          }
        } catch {
          /* ignore poll errors */
        }
      }
      if (changed) {
        void refreshPrepQueue();
        loadApplications();
        loadStats();
      }
    }, 1500);
    return () => clearInterval(interval);
  }, [activePrepIds, loadApplications, loadStats, refreshPrepQueue, prefetchWizardQuestions]);

  function startQwenPrep(opts: { appId: string; company?: string; role?: string }) {
    setError("");
    setMessage("");

    if (prepQueue && prepQueue.available <= 0) {
      setError(`Prep queue full (${prepQueue.queued}/${prepQueue.maxQueue}). Wait for running jobs to finish.`);
      return;
    }

    const key = opts.appId;
    if (!key || preparing.has(key)) return;

    const alreadyQueued = Boolean(
      prepQueue?.queuedApplicationIds.includes(key)
      || prepQueue?.activeApplicationIds.includes(key),
    );
    if (alreadyQueued) {
      prepStartedAtRef.current[key] = prepStartedAtRef.current[key] ?? Date.now();
      setActivePrepIds((prev) => new Set(prev).add(key));
      setMessage(`Prep already running for ${opts.company || "this application"} — Playwright is working in the background.`);
      return;
    }

    prepStartedAtRef.current[key] = Date.now();
    setPreparing((prev) => new Set(prev).add(key));
    window.dispatchEvent(new CustomEvent("qwen-prep-started"));

    void (async () => {
      try {
        const started = await qwenPrepareApplication(opts.appId);

        const nextAppId = started.applicationId;
        setActivePrepIds((prev) => new Set(prev).add(nextAppId));
        dispatchQwenContext(nextAppId, opts.company, opts.role);
        void refreshPrepQueue();
        const queue = started.queue;
        setMessage(
          queue
            ? `Queued prep for ${opts.company || "this application"} (${queue.running} running, ${queue.waiting} waiting).`
            : `Qwen is preparing ${opts.company || "this application"} — watch the preparing animation on the card.`,
        );
        setHighlightAppId(nextAppId);
        loadApplications();
        loadStats();
        window.setTimeout(() => {
          document.getElementById(`aa-app-${nextAppId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 300);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to start Qwen prep");
      } finally {
        setPreparing((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
      }
    })();
  }

  useEffect(() => {
    if (!focusAppId || bootstrapping) return;
    if (focusScrollDoneRef.current === focusAppId) return;
    focusScrollDoneRef.current = focusAppId;

    setHighlightAppId(focusAppId);
    queueAnalyzeRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

    const scrollTimer = window.setTimeout(() => {
      document.getElementById(`aa-app-${focusAppId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 250);

    const clearTimer = window.setTimeout(() => setHighlightAppId(null), 8000);
    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
    };
  }, [focusAppId, bootstrapping]);

  async function handleResume(app: Application) {
    startQwenPrep({ appId: app.id, company: app.companyName, role: app.roleTitle });
  }

  async function handleFocusBrowser(appId: string, app?: Application) {
    setError("");
    try {
      const focused = await openApplicationReview(appId, { force: false });
      setReviewSessions((prev) => ({
        ...prev,
        [appId]: {
          status: focused.browserOpen ? "browser_open" : prev[appId]?.status || "ready",
          message: focused.message || "Brought the application window to the front.",
          browserOpen: Boolean(focused.browserOpen),
          updatedAt: Date.now(),
        },
      }));
      if (focused.alreadyOpen || focused.browserOpen) {
        setMessage("Brought the open application window to the front — check for a Chromium window.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to focus browser");
    }
  }

  async function handleOpenInBrowser(appId: string, app?: Application) {
    setError("");
    const gate = profileGate[appId];
    const { needsAiAnalysis, profileBlocked, pendingCount } = resolveProfileGate(
      app ?? { id: appId } as Application,
      gate,
    );
    if (needsAiAnalysis && app) {
      await runPostPrepFieldAnalysis(app);
      const res = await getPendingFields(app.id, { useAi: false });
      const data = applyPendingApiResponse(res);
      if (data.pending.length > 0) {
        setError(`Answer ${data.pending.length} profile question(s) before opening the browser.`);
        return;
      }
    } else if (profileBlocked && pendingCount > 0) {
      setError(`Answer ${pendingCount} profile question(s) before opening the browser.`);
      return;
    }

    setOpeningReview(appId);
    markOpeningStarted(appId);
    const hasReplayPlan =
      Boolean(app?.hasSavedAutofillState ?? app?.quickApplyAvailable)
      && (app?.autofillStepCount ?? app?.quickApplyStepCount ?? 0) > 0;
    setMessage(
      hasReplayPlan
        ? "Quick apply — opening Chrome with saved Playwright steps…"
        : "Start prep — Playwright is mapping fields with Qwen…",
    );
    setReviewSessions((prev) => ({
      ...prev,
      [appId]: {
        status: "opening",
        message: hasReplayPlan ? "Quick apply — replaying saved steps…" : "Launching browser and filling saved fields…",
        browserOpen: false,
        elapsedSec: 0,
        updatedAt: Date.now(),
      },
    }));
    dispatchQwenContext(appId, app?.companyName, app?.roleTitle);
    pushLiveFloat(hasReplayPlan ? "Quick apply — replaying saved steps…" : "Launching browser and filling saved fields…", "review_open_start");
    let opened: Awaited<ReturnType<typeof openApplicationReview>>;
    try {
      opened = await openApplicationReview(appId, { force: false });
      if ((opened.alreadyOpen || opened.browserOpen) && !hasReplayPlan) {
        await loadApplications();
        await loadStats();
        setReviewSessions((prev) => ({
          ...prev,
          [appId]: {
            status: "browser_open",
            message: opened.message || "Application form is already open in Chrome.",
            browserOpen: true,
            updatedAt: Date.now(),
          },
        }));
        setMessage(opened.message || "Brought the open application window to the front.");
        setOpeningReview(null);
        clearOpeningStarted(appId);
        return;
      }
      if (opened.status === "opening") {
        await loadApplications();
        await loadStats();
        return;
      }
      if (!opened.success && !hasReplayPlan) {
        opened = await openApplicationReview(appId, { force: true });
      }
      await loadApplications();
      await loadStats();

      if (opened.status === "opening") {
        setReviewSessions((prev) => ({
          ...prev,
          [appId]: {
            status: "opening",
            message: opened?.message || "Launching browser and filling saved fields…",
            browserOpen: false,
            elapsedSec: 0,
            updatedAt: Date.now(),
          },
        }));
        return;
      }

      if (opened.status === "preparing" || opened.status === "busy") {
        setError(opened.message || "This application is still being prepared — wait for Qwen to finish.");
        setReviewSessions((prev) => ({
          ...prev,
          [appId]: {
            status: opened.status as ReviewSessionStatus["status"],
            message: opened.message || "Prep still running",
            browserOpen: false,
            updatedAt: Date.now(),
          },
        }));
        setOpeningReview(null);
        clearOpeningStarted(appId);
        return;
      }

      if (opened.status === "profile_incomplete") {
        const blockedCount =
          (opened as { pendingFieldCount?: number }).pendingFieldCount ??
          profileGate[appId]?.count ??
          app?.pendingFieldCount ??
          0;
        handlePendingChange(appId, blockedCount, false, false);
        setError(opened.message || "Answer profile questions before opening the browser.");
        setReviewSessions((prev) => ({
          ...prev,
          [appId]: {
            status: "profile_incomplete",
            message: opened.message || "Answer profile questions before opening the browser.",
            browserOpen: false,
            readyForBrowser: false,
            pendingFieldCount: blockedCount,
            updatedAt: Date.now(),
          },
        }));
        setOpeningReview(null);
        clearOpeningStarted(appId);
        return;
      }

      const reviewStatus = (opened.status as ReviewSessionStatus["status"]) ||
        (opened.browserOpen ? "browser_open" : opened.success ? "ready" : "failed");

      setReviewSessions((prev) => ({
        ...prev,
        [appId]: {
          status: reviewStatus,
          message: opened.message || (opened.browserOpen
            ? "Application form is open in your browser — finish there and submit manually."
            : "Could not open the application form."),
          browserOpen: Boolean(opened.browserOpen),
          updatedAt: Date.now(),
        },
      }));

      if (opened.browserOpen && !opened.alreadyOpen) {
        setMessage("Browser opened — submit on the job site and CareerOS will mark it submitted automatically.");
      } else if (opened.alreadyOpen) {
        setMessage("Brought the open application window to the front — check for a Chromium window.");
      } else if (!opened.success) {
        setError(opened.message || "Could not open the application form. Try Click to complete again.");
      }
      setOpeningReview(null);
      clearOpeningStarted(appId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to open browser";
      if (/already being prepared|still preparing|prep still running|application is busy/i.test(msg)) {
        markOpeningStarted(appId);
        setReviewSessions((prev) => ({
          ...prev,
          [appId]: {
            status: "opening",
            message: msg,
            browserOpen: false,
            updatedAt: Date.now(),
          },
        }));
        return;
      }
      setError(msg);
      setReviewSessions((prev) => ({
        ...prev,
        [appId]: { status: "failed", message: msg, browserOpen: false, updatedAt: Date.now() },
      }));
      setOpeningReview(null);
      clearOpeningStarted(appId);
    } finally {
      void pollReviewStatuses();
    }
  }

  async function handleCloseBrowser(appId: string) {
    setError("");
    setClosingBrowser(appId);
    try {
      await closeApplicationBrowser(appId);
      setReviewSessions((prev) => ({
        ...prev,
        [appId]: {
          status: "ready",
          message: "Ready — click Complete application to open the form.",
          browserOpen: false,
          updatedAt: Date.now(),
        },
      }));
      setMessage("Browser session cleared — you can open the form again when ready.");
      await loadApplications();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to clear browser session");
    } finally {
      setClosingBrowser(null);
      void pollReviewStatuses();
    }
  }

  async function handleToggleSubmitted(app: Application, mark: boolean) {
    setError("");
    try {
      const res = mark ? await markSubmitted(app.id) : await unmarkSubmitted(app.id);
      const nowSubmitted = res.submitted ?? mark;
      setMessage(
        nowSubmitted
          ? "Marked as submitted manually."
          : "Submission mark removed — application moved back for review.",
      );
      await loadApplications();
      await loadStats();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update submission status");
    }
  }

  async function handleAnswerQuestions(app: Application) {
    setError("");

    const cached = wizardDataByApp[app.id] ?? wizardDataFromApplication(app);
    if (cached?.pending.length) {
      if (!wizardDataByApp[app.id]) {
        setWizardDataByApp((prev) => ({ ...prev, [app.id]: cached }));
      }
      handlePendingChange(
        app.id,
        cached.pending.length,
        Boolean(app.readyForBrowser),
        false,
        true,
      );
      setWizardOpenAppId(app.id);
      return;
    }

    setWizardOpenAppId(app.id);
    const useAi = !app.aiAnalyzed;
    setWizardLoadingAppId(app.id);
    if (useAi) {
      handlePendingChange(app.id, app.missingCount ?? 0, false, true);
    }

    try {
      const res = await getPendingFields(app.id, { useAi });
      const data = applyPendingApiResponse(res);
      setWizardDataByApp((prev) => ({ ...prev, [app.id]: data }));
      handlePendingChange(app.id, data.pending.length, Boolean(res.readyForBrowser), false, Boolean(res.aiAnalyzed));
      if (!data.pending.length) {
        setWizardOpenAppId(null);
        await loadApplications();
        await loadStats();
        setMessage(`${app.companyName}: All fields matched from your profile — no new answers needed.`);
        return;
      }
    } catch (e) {
      setWizardOpenAppId(null);
      handlePendingChange(app.id, app.missingCount ?? 0, false, false);
      setError(e instanceof Error ? e.message : "Could not load profile questions");
    } finally {
      setWizardLoadingAppId(null);
    }
  }

  const gatedApps = useMemo(
    () =>
      applications.filter((a) => {
        const gate = profileGate[a.id];
        return resolveProfileGate(a, gate).profileBlocked;
      }),
    [applications, profileGate],
  );

  const unifiedAppIds = useMemo(() => gatedApps.map((app) => app.id), [gatedApps]);

  const useUnifiedWizard = unifiedAppIds.length >= 2;

  const appsWithMissingFields = useMemo(
    () =>
      applications.filter(
        (a) =>
          (a.missingCount ?? 0) > 0 ||
          (profileGate[a.id]?.count ?? 0) > 0 ||
          (a.pendingFieldCount ?? 0) > 0,
      ),
    [applications, profileGate],
  );

  const openMissingFieldsOverview = useCallback(async () => {
    const totalMissing = stats?.fieldTotals?.missing ?? 0;
    if (totalMissing === 0 && appsWithMissingFields.length === 0) {
      setMessage("No missing fields across your applications.");
      return;
    }

    const targetApps =
      appsWithMissingFields.length > 0 ? appsWithMissingFields : applications.filter((a) => (a.missingCount ?? 0) > 0);
    const targetIds = targetApps.map((a) => a.id);
    const singleApp = targetApps.length === 1 ? targetApps[0] : null;

    setMissingOverview({
      open: true,
      loading: true,
      data: null,
      appIds: targetIds,
      singleApp,
      rawOccurrenceCount: 0,
    });
    setError("");

    try {
      pushLiveFloat("Qwen is checking missing questions against your profile…", "analyze_progress");
      const res = await getAggregatePendingFields(targetIds.length ? targetIds : undefined, { useAi: true });
      const data = applyPendingApiResponse(res);
      setMissingOverview({
        open: true,
        loading: false,
        data,
        appIds: res.applicationIds?.length ? res.applicationIds : targetIds,
        singleApp,
        rawOccurrenceCount: res.rawOccurrenceCount ?? data.pending.length,
      });
      if (singleApp) {
        setWizardDataByApp((prev) => ({ ...prev, [singleApp.id]: data }));
      }
    } catch (err) {
      setMissingOverview((prev) => ({ ...prev, open: false, loading: false }));
      setError(err instanceof Error ? err.message : "Could not load missing questions");
    }
  }, [appsWithMissingFields, applications, pushLiveFloat, stats?.fieldTotals?.missing]);

  const closeMissingOverview = useCallback(() => {
    setMissingOverview({
      open: false,
      loading: false,
      data: null,
      appIds: [],
      singleApp: null,
      rawOccurrenceCount: 0,
    });
  }, []);

  const firstActivePrepId = activePrepIds.size ? [...activePrepIds][0] : undefined;
  const liveFloatOpen = Boolean(activePrepIds.size || openingReview || liveFloatHold);
  const liveFloatApp = firstActivePrepId
    ? applications.find((a) => a.id === firstActivePrepId)
    : openingReview
      ? applications.find((a) => a.id === openingReview)
      : undefined;
  const liveFloatTitle = openingReview && liveFloatApp
    ? `Opening · ${liveFloatApp.companyName}`
    : liveFloatApp
      ? `Qwen · ${liveFloatApp.companyName}`
      : "Qwen · working";
  const liveFloatElapsed = openingReview
    ? getOpeningElapsed(openingReview, reviewSessions[openingReview])
    : firstActivePrepId
      ? getPrepElapsed(firstActivePrepId)
      : 0;
  void openingTick;

  return (
    <div className="aa-dashboard">
      <QwenLiveFloat
        open={liveFloatOpen}
        title={liveFloatTitle}
        subtitle={
          openingReview
            ? "Launching Chromium and filling saved answers — check for a browser window"
            : liveFloatApp?.roleTitle
        }
        applicationId={firstActivePrepId ?? openingReview ?? undefined}
        elapsedSec={liveFloatElapsed}
        localLines={liveFloatLines}
      />
      {bootstrapping && (
        <div className="aa-bootstrapping" role="status" aria-label="Loading applications">
          <span className="page-loading-bar" />
          <p className="muted">
            {applications.length > 0 ? "Refreshing applications…" : "Loading applications…"}
          </p>
        </div>
      )}
      {applicationsLoadError && (
        <div className="aa-load-error" role="alert">
          <p className="aa-error">{applicationsLoadError}</p>
          {applications.length > 0 ? (
            <p className="muted text-sm">Showing last loaded cards — click Refresh to update.</p>
          ) : (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void loadApplications()}>
              Retry loading applications
            </button>
          )}
        </div>
      )}
      {message && <p className="aa-message" role="status">{message}</p>}
      {error && <p className="aa-error" role="alert">{error}</p>}
      {prepQueue && (prepQueue.queued > 0 || (prepQueue.openBrowserCount ?? 0) > 0) ? (
        <p className="aa-message" role="status">
          Prep queue: {prepQueue.running} running · {prepQueue.waiting} waiting · {prepQueue.available} slots left
          {" "}(max {prepQueue.maxConcurrent} parallel, {prepQueue.maxQueue} total)
          {(prepQueue.openBrowserCount ?? 0) > 0
            ? ` · ${prepQueue.openBrowserCount} browser window${prepQueue.openBrowserCount === 1 ? "" : "s"} open`
            : ""}
        </p>
      ) : null}

      {missingOverview.loading && (
        <SidePanelPortal
          open
          onClose={() => {}}
          backdropAriaLabel="Loading questions"
          role="status"
          ariaLive="polite"
        >
          <div className="aa-wizard-panel-inner">
            <header className="aa-wizard-header">
              <div>
                <p className="aa-wizard-eyebrow">Missing fields</p>
                <h2>Loading questions…</h2>
              </div>
            </header>
            <div className="aa-wizard-body aa-wizard-body--loading">
              <span className="aa-wizard-loading-spinner" aria-hidden />
              <p><strong>Checking your profile with Qwen…</strong></p>
              <p className="muted">Collecting answers needed across your applications.</p>
            </div>
          </div>
        </SidePanelPortal>
      )}

      {missingOverview.open && !missingOverview.loading && missingOverview.data && (
        <ProfileQuestionsWizard
          open
          onClose={closeMissingOverview}
          layout="panel"
          mode={missingOverview.singleApp ? "single" : "unified"}
          appId={missingOverview.singleApp?.id}
          companyName={
            missingOverview.singleApp?.companyName ??
            `${missingOverview.appIds.length} application${missingOverview.appIds.length === 1 ? "" : "s"}`
          }
          roleTitle={missingOverview.singleApp?.roleTitle ?? "Missing answers"}
          pending={missingOverview.data.pending}
          profilePending={missingOverview.data.profilePending}
          applicationPending={missingOverview.data.applicationPending}
          profileKeysMissing={missingOverview.data.profileKeysMissing}
          applicationCount={missingOverview.appIds.length}
          rawOccurrenceCount={missingOverview.rawOccurrenceCount}
          onComplete={async () => {
            closeMissingOverview();
            await refreshAll();
            setMessage("Answers saved. Missing field counts will update shortly.");
          }}
        />
      )}

      <p className="aa-safety-note">
        Final submission is always manual. Automation never clicks Submit, Apply, or equivalent buttons.
      </p>

      {/* Live stats & charts */}
      <section className="aa-section aa-panel aa-panel--stats">
        <div className="aa-panel-header">
          <div>
            <span className="aa-section-eyebrow">Overview</span>
            <h2>Live dashboard</h2>
          </div>
          {liveMode && <span className="qwen-live-badge">Live</span>}
        </div>
        <div className="aa-stats-grid">
          <div className="aa-stat-card aa-stat-card--apps">
            <span>Applications</span>
            <strong>{stats?.totalApplications ?? applications.length}</strong>
            <p>{stats?.statusCounts?.needs_review ?? 0} quick apply</p>
          </div>
          <div className="aa-stat-card aa-stat-card--verified">
            <span>Verified fields</span>
            <strong>{stats?.fieldTotals?.verified ?? 0}</strong>
            <p>Across all drafts</p>
          </div>
          <button
            type="button"
            className="aa-stat-card aa-stat-card--missing aa-stat-card--clickable"
            onClick={() => void openMissingFieldsOverview()}
            aria-label={`${stats?.fieldTotals?.missing ?? 0} missing fields — open to answer questions`}
            title="View and answer missing profile questions"
          >
            <span>Missing fields</span>
            <strong>{stats?.fieldTotals?.missing ?? 0}</strong>
            <p>Need manual input · Click to answer</p>
          </button>
          <div className={`aa-stat-card aa-stat-card--prep${liveMode ? " aa-stat-card--live" : ""}`}>
            <span>Active prep</span>
            <strong>{liveMode ? "Running" : "Idle"}</strong>
            <p>{stats?.activePrep?.step || "No job in progress"}</p>
          </div>
        </div>
        <div className="aa-charts-row">
          <div className="aa-chart-panel">
            <h3>Queue by status</h3>
            <StatusBarChart counts={stats?.statusCounts ?? {}} total={stats?.totalApplications ?? 0} />
          </div>
          <div className="aa-chart-panel">
            <h3>Field breakdown</h3>
            <FieldDonutChart
              verified={stats?.fieldTotals?.verified ?? 0}
              missing={stats?.fieldTotals?.missing ?? 0}
              needsReview={stats?.fieldTotals?.needsReview ?? 0}
            />
          </div>
        </div>
      </section>

      {/* Provider status */}
      <section className="aa-section aa-panel aa-panel--compact">
        <div className="aa-panel-header">
          <div>
            <span className="aa-section-eyebrow">Integrations</span>
            <h2>Supported providers</h2>
          </div>
        </div>
        <div className="aa-provider-list">
          {providers.map((p) => (
            <span key={p.name} className={`aa-provider ${p.supported ? "aa-provider--supported" : "aa-provider--unsupported"}`}>
              {p.name} {p.supported ? "✓" : "(coming soon)"}
            </span>
          ))}
        </div>
      </section>

      {/* Application Queue */}
      <section id="application-queue" className="aa-section aa-panel aa-panel--queue">
        <div className="aa-panel-header">
          <div>
            <span className="aa-section-eyebrow">Pipeline</span>
            <h2>Application queue</h2>
          </div>
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => void refreshAll()}
            disabled={bootstrapping}
          >
            Refresh
          </button>
        </div>
        <p className="aa-queue-hint muted">
          Add jobs from <a href="/jobs/discover">Job Scraper</a> — prep starts automatically in the background. When ready, use{" "}
          <strong>Quick apply</strong> to open the form with your saved answers.
        </p>
        <div ref={queueAnalyzeRef} />
        {useUnifiedWizard && (
          <UnifiedQuestionsGate
            ref={unifiedGateRef}
            appIds={unifiedAppIds}
            applicationCount={unifiedAppIds.length}
            onAppsAnalyzed={(apps) => {
              for (const item of apps) {
                handlePendingChange(item.appId, item.pendingCount, item.ready, false, true);
              }
            }}
            onComplete={({ reprepStarted }) => {
              void loadApplications();
              void loadStats();
              if (reprepStarted) {
                setMessage("Answers saved — Qwen is re-running prep on ready applications.");
              } else {
                setMessage("Unified answers saved across your applications.");
              }
            }}
          />
        )}
        {!useUnifiedWizard && gatedApps.length > 0 && (
          <div className="aa-profile-gate-banner" role="status">
            <strong>{gatedApps.length} application{gatedApps.length === 1 ? "" : "s"}</strong>
            {" need "}
            <strong>
              {gatedApps.reduce(
                (sum, a) => sum + resolveProfileGate(a, profileGate[a.id]).pendingCount,
                0,
              )} answer
              {gatedApps.reduce(
                (sum, a) => sum + resolveProfileGate(a, profileGate[a.id]).pendingCount,
                0,
              ) === 1 ? "" : "s"}
            </strong>
            {" before you can open the browser."}
          </div>
        )}
        {applicationsLoading && applications.length === 0 ? (
          <ApplicationQueueSkeleton count={3} />
        ) : null}
        {!applicationsLoading && applications.length === 0 && !applicationsLoadError ? (
          <p className="muted">No applications yet. Discover jobs and start an application to get started.</p>
        ) : null}
        {!applicationsLoading && applications.length === 0 && applicationsLoadError ? (
          <p className="muted">Could not load your application queue. Use Retry above or check that the API is running on port 8000.</p>
        ) : null}
        {QUEUE_GROUPS.map((group) => {
          const items = applications.filter((app) => {
            const gate = profileGate[app.id];
            const readiness = resolveApplicationReadiness(app, gate);
            const isActivePrep = appIsActivelyPreparing(app.id, app, prepQueue, preparing, activePrepIds);
            return resolveQueueGroupKeyForApp(app, { readiness, isPreparing: isActivePrep }) === group.key;
          });
          if (items.length === 0) return null;
          return (
            <div key={group.key} className={`aa-queue-group aa-queue-group--${group.key.replace(/_/g, "-")}`}>
              <div className="aa-queue-group-header">
                <h3>{group.label}</h3>
                <span className="aa-queue-group-count">{items.length}</span>
              </div>
              <div className="aa-queue-grid">
              {items.map((app) => {
                const reviewSession = reviewSessions[app.id];
                const isOpening = openingReview === app.id || reviewSession?.status === "opening";
                const isBrowserOpen =
                  reviewSession?.status === "browser_open"
                  || Boolean(prepQueue?.openBrowserApplicationIds?.includes(app.id));
                const gate = profileGate[app.id];
                const readiness = resolveApplicationReadiness(app, gate);
                const { pendingCount, profileBlocked, gateLoading, needsAiAnalysis } = readiness;
                const isWizardLoading = wizardLoadingAppId === app.id;
                const isActivePrep = appIsActivelyPreparing(app.id, app, prepQueue, preparing, activePrepIds);
                const isPreparingNow = preparing.has(app.id) || (app.jobId ? preparing.has(app.jobId) : false);
                const prepElapsedSec = isActivePrep ? getPrepElapsed(app.id) : 0;
                const displayGroupKey = resolveQueueGroupKeyForApp(app, { readiness, isPreparing: isActivePrep || isPreparingNow });
                const statusAccent = STATUS_ACCENT[displayGroupKey] || "slate";
                const openingElapsedSec = isOpening ? getOpeningElapsed(app.id, reviewSession) : 0;
                void openingTick;
                return (
                <div
                  key={app.id}
                  id={`aa-app-${app.id}`}
                  className={highlightAppId === app.id ? "aa-queue-card-wrap aa-queue-card-wrap--highlight" : "aa-queue-card-wrap"}
                >
                <ApplicationQueueCard
                  app={app}
                  statusAccent={statusAccent}
                  reviewSession={reviewSession}
                  isOpening={isOpening}
                  isBrowserOpen={isBrowserOpen}
                  isAnalyzing={gateLoading}
                  isWizardLoading={isWizardLoading}
                  gateLoading={gateLoading}
                  profileBlocked={profileBlocked}
                  readiness={readiness}
                  needsAiAnalysis={needsAiAnalysis}
                  pendingCount={pendingCount}
                  isPreparing={isPreparingNow}
                  isActivePrep={isActivePrep}
                  prepElapsedSec={prepElapsedSec}
                  openingElapsedSec={openingElapsedSec}
                  analyzeElapsedSec={0}
                  closingBrowser={closingBrowser === app.id}
                  onFocusBrowser={() => void handleFocusBrowser(app.id, app)}
                  onResume={() => void handleResume(app)}
                  onAnswerQuestions={() => void handleAnswerQuestions(app)}
                  onOpenInBrowser={() => void handleOpenInBrowser(app.id, app)}
                  onToggleSubmitted={(submitted) => void handleToggleSubmitted(app, submitted)}
                  onArchive={async () => {
                    await archiveApplication(app.id);
                    loadApplications();
                    loadStats();
                  }}
                  onCloseBrowser={() => void handleCloseBrowser(app.id)}
                  reviewBannerSlot={
                    <>
                      {(isOpening || reviewSession?.status === "opening") && (
                        <div className="aa-card-analyze-progress aa-card-open-progress" role="status">
                          <span className="page-loading-bar" />
                          <p className="muted">
                            Quick apply · {openingElapsedSec}s — look for a Chromium window
                          </p>
                        </div>
                      )}
                      <ReviewStatusBanner
                        session={reviewSession}
                        openingElapsedSec={isOpening ? openingElapsedSec : undefined}
                        onBrowserClosed={() => void handleCloseBrowser(app.id)}
                        onAnswerQuestions={
                          profileBlocked
                            ? () => void handleAnswerQuestions(app)
                            : undefined
                        }
                        answeringQuestions={isWizardLoading || gateLoading}
                        closingBrowser={closingBrowser === app.id}
                      />
                    </>
                  }
                  prepReportSlot={<PrepReportPanel app={app} embedded />}
                  gateSlot={
                    <ProfileQuestionsGate
                      ref={(handle) => {
                        gateRefs.current[app.id] = handle;
                      }}
                      app={app}
                      hideWizard={false}
                      hideBanner
                      wizardData={wizardDataByApp[app.id] ?? null}
                      wizardOpen={wizardOpenAppId === app.id}
                      wizardLoading={wizardLoadingAppId === app.id}
                      onWizardOpenChange={(open) => {
                        setWizardOpenAppId(open ? app.id : (current) => (current === app.id ? null : current));
                      }}
                      onWizardLoadError={setError}
                      deferAutoOpen={useUnifiedWizard}
                      onPendingChange={handlePendingChange}
                      onWizardDataLoaded={(appId, data) => {
                        setWizardDataByApp((prev) => ({ ...prev, [appId]: data }));
                      }}
                      onSaved={({ readyForBrowser: ready, reprepStarted, pendingCount: savedPending }) => {
                        void loadApplications();
                        void loadStats();
                        setWizardOpenAppId(null);
                        if (reprepStarted) {
                          setActivePrepIds((prev) => new Set(prev).add(app.id));
                          setMessage("Profile complete — Qwen is re-running prep with your saved answers.");
                        } else if (ready) {
                          setMessage("All profile questions saved — you can open the browser.");
                          handlePendingChange(app.id, 0, true, false, true);
                          setWizardOpenAppId(null);
                        } else {
                          const remaining = savedPending ?? profileGate[app.id]?.count ?? 0;
                          handlePendingChange(app.id, remaining, false, false, true);
                          setMessage(
                            remaining > 0
                              ? `Saved — ${remaining} question${remaining === 1 ? "" : "s"} remaining.`
                              : "Answers saved.",
                          );
                        }
                      }}
                    />
                  }
                  errorSlot={
                    app.errors.length > 0 ? (
                      <p className="aa-error">{formatAppError(app.errors[0])}</p>
                    ) : null
                  }
                />
                </div>
                );})}
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}
