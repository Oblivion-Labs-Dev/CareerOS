import { type PrepQueueStatus } from "@/lib/application-assistant-api";
import { type PendingQuestion } from "@/components/application-assistant/profile-questions-wizard";
import { resolveApplicationReadiness, resolveQueueGroupKey } from "@/components/application-assistant/application-readiness";
import {
  isConsentQuestion,
  isFreeTextApplicationQuestion,
  looksLikePhoneCountryOptions,
  normalizeFieldOptions,
} from "@/lib/profile-form-options";

export type Application = {
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

export type DashboardStats = {
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

export const STATUS_LABELS: Record<string, string> = {
  ready_to_prepare: "Ready to prepare",
  in_progress: "In progress",
  needs_review: "Quick apply",
  blocked: "Blocked",
  ready_for_final_review: "Ready for final review",
  submitted_manually: "Submitted manually",
  archived: "Archived",
};

export const STATUS_ACCENT: Record<string, string> = {
  ready_to_prepare: "cyan",
  in_progress: "violet",
  needs_review: "amber",
  blocked: "rose",
  ready_for_final_review: "emerald",
  submitted_manually: "teal",
  archived: "slate",
};

export const REVIEW_STATUS_LABELS: Record<string, string> = {
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

export const QUEUE_GROUPS = [
  { key: "needs_review", label: "Quick apply" },
  { key: "ready_to_prepare", label: "Start prep" },
  { key: "blocked", label: "Blocked" },
  { key: "ready_for_final_review", label: "Ready for final review" },
  { key: "submitted_manually", label: "Submitted manually" },
  { key: "archived", label: "Archived" },
];

export type ReviewSessionStatus = {
  status: "idle" | "opening" | "browser_open" | "ready" | "failed" | "profile_incomplete" | "submitted" | "preparing" | "busy";
  message: string;
  browserOpen: boolean;
  readyForBrowser?: boolean;
  alreadyOpen?: boolean;
  pendingFieldCount?: number;
  verifiedCount?: number;
  missingCount?: number;
  progress?: number;
  jobUrl?: string;
  elapsedSec?: number;
  submitted?: boolean;
  submittedAt?: string;
  submissionSource?: string;
  updatedAt?: number;
};

export type ProfileGateEntry = { count: number; ready: boolean; loading?: boolean; aiAnalyzed?: boolean };

export function formatAppError(err: Application["errors"][number] | undefined): string {
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

export function resolveProfileGate(app: Application, gate?: ProfileGateEntry) {
  const readiness = resolveApplicationReadiness(app, gate);
  const canOpenBrowser =
    ["needs_review", "in_progress", "blocked"].includes(app.status) &&
    !readiness.profileBlocked &&
    !readiness.gateLoading &&
    !readiness.needsAiAnalysis &&
    readiness.readyForBrowser;
  return { ...readiness, canOpenBrowser };
}

export function stripOpeningMessageSuffix(message: string): string {
  return message.replace(/\s*\(\d+s\)\s*$/i, "").replace(/(…|\.\.\.)\s*\(\d+s\)/gi, "$1");
}

export function appIsActivelyPreparing(
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

export function resolveQueueGroupKeyForApp(
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

export type AppWizardData = {
  pending: PendingQuestion[];
  profilePending: PendingQuestion[];
  applicationPending: PendingQuestion[];
  profileKeysMissing: string[];
};

export function sanitizeWizardQuestion(field: PendingQuestion): PendingQuestion {
  let next = { ...field };
  const options = normalizeFieldOptions(next.options);
  if (looksLikePhoneCountryOptions(options)) {
    next = { ...next, options: [] };
  }
  if (isConsentQuestion(next)) {
    next = { ...next, fieldType: "boolean" };
  } else if (isFreeTextApplicationQuestion(next)) {
    next = { ...next, fieldType: "textarea" };
  }
  return next;
}
