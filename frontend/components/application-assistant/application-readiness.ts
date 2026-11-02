/** Shared readiness rules for queue grouping, card CTAs, and pipeline labels. */

export type ReadinessApp = {
  status: string;
  readyForBrowser?: boolean;
  hasSavedAutofillState?: boolean;
  quickApplyAvailable?: boolean;
  prepRequired?: boolean;
  autofillStepCount?: number;
  quickApplyStepCount?: number;
  quickApplyLabel?: string;
  missingCount?: number;
  pendingFieldCount?: number;
  aiAnalyzed?: boolean;
  lastPrepFailed?: boolean;
};

export type ProfileGateSnapshot = {
  count?: number;
  ready?: boolean;
  loading?: boolean;
  aiAnalyzed?: boolean;
};

export type ResolvedReadiness = {
  pendingCount: number;
  readyForBrowser: boolean;
  profileBlocked: boolean;
  gateLoading: boolean;
  needsAiAnalysis: boolean;
  aiAnalyzed: boolean;
  hasSavedAutofill: boolean;
  savedStepCount: number;
  needsStartPrep: boolean;
  canQuickApply: boolean;
};

function savedStepCount(app: ReadinessApp): number {
  return app.autofillStepCount ?? app.quickApplyStepCount ?? 0;
}

export function isTerminalApplicationStatus(status: string): boolean {
  return status === "submitted_manually" || status === "archived";
}

export function resolveApplicationReadiness(
  app: ReadinessApp,
  gate?: ProfileGateSnapshot,
): ResolvedReadiness {
  const terminal = isTerminalApplicationStatus(app.status);
  const gateLoading = Boolean(gate?.loading);
  const aiAnalyzed = Boolean(gate?.aiAnalyzed ?? app.aiAnalyzed);
  const rawMissing = app.missingCount ?? 0;
  const needsAiAnalysis = rawMissing > 0 && !aiAnalyzed;

  const pendingCount = aiAnalyzed
    ? (gate?.count ?? app.pendingFieldCount ?? rawMissing)
    : rawMissing;

  let readyForBrowser: boolean;
  if (gateLoading) {
    readyForBrowser = false;
  } else if (aiAnalyzed && gate) {
    readyForBrowser = Boolean(gate.ready);
  } else if (app.readyForBrowser) {
    readyForBrowser = true;
  } else if (rawMissing === 0) {
    readyForBrowser = true;
  } else {
    readyForBrowser = false;
  }

  const profileBlocked =
    !needsAiAnalysis &&
    (gateLoading || (!readyForBrowser && pendingCount > 0));

  const steps = savedStepCount(app);
  const hasSavedAutofill =
    Boolean(app.hasSavedAutofillState ?? app.quickApplyAvailable) && steps > 0;
  const needsStartPrep =
    !terminal && readyForBrowser && !hasSavedAutofill && !profileBlocked && !needsAiAnalysis;
  const canQuickApply =
    !terminal && readyForBrowser && hasSavedAutofill && !profileBlocked && !needsAiAnalysis;

  return {
    pendingCount,
    readyForBrowser,
    profileBlocked,
    gateLoading,
    needsAiAnalysis,
    aiAnalyzed,
    hasSavedAutofill,
    savedStepCount: steps,
    needsStartPrep,
    canQuickApply,
  };
}

export function resolveQueueGroupKey(
  app: ReadinessApp,
  opts: {
    readyForBrowser: boolean;
    profileBlocked: boolean;
    needsAiAnalysis: boolean;
    canQuickApply: boolean;
    needsStartPrep?: boolean;
    isPreparing?: boolean;
    lastPrepFailed?: boolean;
  },
): string {
  if (app.status === "archived") return "archived";
  if (app.status === "submitted_manually") return "submitted_manually";
  if (app.status === "ready_for_final_review") return "ready_for_final_review";
  if (app.status === "blocked") return "blocked";

  if (opts.needsAiAnalysis || opts.profileBlocked || !opts.readyForBrowser) {
    return "ready_to_prepare";
  }

  if ((opts.needsStartPrep || opts.lastPrepFailed) && !opts.canQuickApply) {
    return "ready_to_prepare";
  }

  return "needs_review";
}

export type PrimaryAction = {
  label: string;
  disabled: boolean;
  kind: "busy" | "start" | "questions" | "quick_apply" | "focus";
};

export function resolvePrimaryAction(opts: {
  readiness: ResolvedReadiness;
  appStatus?: string;
  isPreparing: boolean;
  isActivePrep: boolean;
  isOpening: boolean;
  isAnalyzing: boolean;
  isBrowserOpen: boolean;
  isWizardLoading: boolean;
  openingElapsedSec: number;
  analyzeElapsedSec: number;
  prepElapsedSec?: number;
  lastPrepFailed?: boolean;
}): PrimaryAction | null {
  const {
    readiness,
    appStatus = "",
    isPreparing,
    isActivePrep,
    isOpening,
    isAnalyzing,
    isBrowserOpen,
    isWizardLoading,
    openingElapsedSec,
    analyzeElapsedSec,
    prepElapsedSec = 0,
    lastPrepFailed = false,
  } = opts;

  if (isTerminalApplicationStatus(appStatus)) {
    return null;
  }

  if (isPreparing || isActivePrep) {
    return {
      label: prepElapsedSec > 0 ? `Preparing… ${prepElapsedSec}s` : "Preparing…",
      disabled: true,
      kind: "busy",
    };
  }

  if (isOpening) {
    return {
      label: readiness.canQuickApply
        ? `Quick apply… ${openingElapsedSec}s`
        : `Starting… ${openingElapsedSec}s`,
      disabled: true,
      kind: "busy",
    };
  }

  if (isAnalyzing || readiness.gateLoading || readiness.needsAiAnalysis) {
    return {
      label: analyzeElapsedSec > 0 ? `Analyzing… ${analyzeElapsedSec}s` : "Analyzing…",
      disabled: true,
      kind: "busy",
    };
  }

  if (isBrowserOpen && readiness.canQuickApply) {
    return { label: "Quick apply", disabled: false, kind: "quick_apply" };
  }

  if (isBrowserOpen) {
    return { label: "Focus Chrome", disabled: false, kind: "focus" };
  }

  if (readiness.profileBlocked) {
    const n = readiness.pendingCount;
    return {
      label: isWizardLoading ? "Loading…" : `Answer ${n} question${n === 1 ? "" : "s"}`,
      disabled: isWizardLoading,
      kind: "questions",
    };
  }

  if (readiness.canQuickApply) {
    return { label: "Quick apply", disabled: false, kind: "quick_apply" };
  }

  if (readiness.needsStartPrep && !isPreparing && !isActivePrep) {
    return {
      label: lastPrepFailed ? "Retry prep" : "Start prep",
      disabled: false,
      kind: "start",
    };
  }

  if (lastPrepFailed) {
    return { label: "Retry prep", disabled: false, kind: "start" };
  }

  if (readiness.readyForBrowser) {
    return { label: "Preparing…", disabled: true, kind: "busy" };
  }

  return null;
}

export function resolveApplicationStage(opts: {
  app: ReadinessApp;
  readiness: ResolvedReadiness;
  isPreparing: boolean;
  isActivePrep: boolean;
  isOpening: boolean;
  isBrowserOpen: boolean;
  lastPrepFailed?: boolean;
}): { index: number; label: string } {
  const { app, readiness, isPreparing, isActivePrep, isOpening, isBrowserOpen, lastPrepFailed = false } = opts;

  if (app.status === "archived") return { index: 4, label: "Archived" };
  if (app.status === "submitted_manually") return { index: 4, label: "Submitted" };
  if (isBrowserOpen) return { index: 3, label: "Browser open" };
  if (app.status === "ready_for_final_review") return { index: 3, label: "Final review" };

  if (isOpening && readiness.canQuickApply) {
    return { index: 3, label: "Applying" };
  }

  if (isPreparing || isActivePrep) {
    return { index: 1, label: "Preparing" };
  }

  if (readiness.needsAiAnalysis) {
    return { index: 2, label: "Analyzing profile" };
  }

  if (readiness.profileBlocked) {
    return { index: 2, label: "Profile questions" };
  }

  if (lastPrepFailed && !readiness.canQuickApply) {
    return { index: 0, label: "Prep failed" };
  }

  if (readiness.needsStartPrep && !isPreparing && !isActivePrep) {
    return { index: 0, label: "Start prep" };
  }

  if (!readiness.readyForBrowser) {
    return { index: 0, label: "Profile setup" };
  }

  if (app.status === "blocked") return { index: 2, label: "Blocked" };
  return { index: 2, label: readiness.canQuickApply ? "Ready to apply" : "Preparing" };
}

export function resolveQuickApplyHint(
  app: ReadinessApp,
  readiness: ResolvedReadiness,
  opts?: { isPreparing?: boolean },
): string | null {
  if (isTerminalApplicationStatus(app.status)) {
    return null;
  }
  if (readiness.profileBlocked) {
    return `${readiness.pendingCount} profile answer${readiness.pendingCount === 1 ? "" : "s"} needed before prep`;
  }
  if (readiness.needsAiAnalysis) {
    return "Analyzing profile questions with Qwen…";
  }
  if (opts?.isPreparing) {
    return "Preparing application in the background…";
  }
  if (readiness.canQuickApply) {
    if (app.quickApplyLabel && !app.quickApplyLabel.includes("Start prep")) {
      return app.quickApplyLabel;
    }
    const steps = readiness.savedStepCount;
    return steps > 0
      ? `Quick apply ready · ${steps} saved step${steps === 1 ? "" : "s"}`
      : "Quick apply ready";
  }
  if (readiness.needsStartPrep) {
    if (app.lastPrepFailed) {
      return "Prep failed — click Retry prep";
    }
    return "Start prep to map application fields";
  }
  if (app.lastPrepFailed) {
    return "Prep failed — click Retry prep";
  }
  if (!readiness.readyForBrowser) {
    return "Complete profile questions first";
  }
  return "Preparing in the background…";
}
