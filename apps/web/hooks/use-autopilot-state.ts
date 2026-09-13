"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getAutopilotEventSource, getAutopilotStatus } from "@/lib/application-assistant-api";

/**
 * Single source of live Autopilot state for the control center.
 *
 * Everything here comes straight off the backend's /autopilot/status payload —
 * no derived "operational" claims are invented client-side. When the backend
 * can't tell us something (no active job, no self-healing history), callers get
 * null/empty and are expected to render an honest empty state rather than a
 * placeholder number.
 */

export type AutopilotWorker = {
  workerId: string;
  slot: number;
  status: string;
  currentJob: { id: string; company: string; title: string } | null;
  currentStep: string;
  startedAt: string;
  error: string;
  jobsCompleted: number;
  jobsFailed: number;
};

export type AutopilotLog = {
  id: string;
  timestamp: string;
  level: string;
  message: string;
  metadata?: Record<string, any>;
};

export type AutopilotCumulative = {
  submitted: number;
  staged: number;
  skipped: number;
  failed: number;
  processed: number;
  queueRemaining: number;
};

export type SelfHealingState = {
  status: string;
  currentRound: number;
  maxRounds: number;
  lastPatchSummary: string;
  patchesApplied: number;
  lastError?: string;
  patchHistory?: any[];
};

export type ConcurrencyMetrics = {
  activeWorkers: number;
  totalWorkers: number;
  avgJobTimeSec: number;
  throughputPerMin: number;
  lockContentionCount: number;
  selfHealingRoundsCompleted: number;
  totalJobsStarted: number;
  totalJobsFinished: number;
};

/** The configuration the running batch is actually using, reported by the
 *  runner rather than echoed from the request the console sent. */
export type AutopilotBatchConfig = {
  batchSize: number;
  minMatchScore: number;
  tierGuardrails: boolean;
  selfHealing: boolean;
  aiModel: string;
  tailoringMode: string;
};

export type AutopilotState = {
  running: boolean;
  /** Raw backend run status: RUNNING | PAUSED | STOPPED | COMPLETED | RECOVERING */
  status: string;
  run: Record<string, any> | null;
  cumulative: AutopilotCumulative | null;
  activeJob: Record<string, any> | null;
  queueSize: number;
  recentLogs: AutopilotLog[];
  workers: AutopilotWorker[];
  concurrency: number;
  concurrencyMetrics: ConcurrencyMetrics | null;
  selfHealing: SelfHealingState | null;
  batchConfig: AutopilotBatchConfig | null;
};

/** What the header badge shows. Derived only from real backend status. */
export type OperationalState = "running" | "recovering" | "paused" | "completed" | "stopped" | "error" | "unknown";

export function resolveOperationalState(state: AutopilotState | null, connectionError: boolean): OperationalState {
  if (connectionError) return "error";
  if (!state) return "unknown";
  if (["analyzing", "patching", "requeuing"].includes(state.selfHealing?.status || "")) return "recovering";
  const raw = (state.status || "").toUpperCase();
  if (raw === "RUNNING") return "running";
  if (raw === "RECOVERING") return "recovering";
  if (raw === "PAUSED") return "paused";
  if (raw === "COMPLETED") return "completed";
  if (raw === "STOPPED") return "stopped";
  return state.running ? "running" : "unknown";
}

export const OPERATIONAL_LABELS: Record<OperationalState, { label: string; detail: string }> = {
  running: { label: "Running", detail: "Applying to jobs" },
  recovering: { label: "Recovering", detail: "Repairing an automation issue" },
  paused: { label: "Paused", detail: "Autopilot is paused" },
  completed: { label: "Idle", detail: "Batch complete — nothing queued to run" },
  stopped: { label: "Stopped", detail: "Not currently applying" },
  error: { label: "Offline", detail: "Can't reach the Autopilot service" },
  unknown: { label: "Unknown", detail: "State unavailable" },
};

export function useAutopilotState(pollMs = 10_000) {
  const [state, setState] = useState<AutopilotState | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const [loading, setLoading] = useState(true);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = (await getAutopilotStatus()) as unknown as AutopilotState;
      setState(res);
      setConnectionError(false);
    } catch {
      setConnectionError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();

    // SSE gives immediate transitions; the interval is only a recovery sync so
    // a dropped stream can't leave the control center showing stale state.
    let es: EventSource | null = null;
    try {
      es = getAutopilotEventSource();
      es.addEventListener("status", (event: MessageEvent) => {
        try {
          setState(JSON.parse(event.data));
          setConnectionError(false);
          setLoading(false);
        } catch {
          /* malformed frame — the poll below still corrects it */
        }
      });
      es.addEventListener("autopilot_event", (event: MessageEvent) => {
        try {
          const payload = JSON.parse(event.data);
          setState((previous) => {
            if (!previous) return previous;
            return {
              ...previous,
              activeJob: payload.company
                ? {
                    company: payload.company,
                    title: payload.title,
                    currentStep: payload.workflowStep,
                    stage: payload.stage,
                    model: payload.model,
                    provider: payload.provider,
                    durationMs: payload.durationMs,
                    message: payload.message,
                  }
                : previous.activeJob,
            };
          });
        } catch {
          /* malformed frame */
        }
      });
      es.addEventListener("log", (event: MessageEvent) => {
        try {
          const log = JSON.parse(event.data) as AutopilotLog;
          if (log.id && typeof log.message === "string") setState(previous => previous ? {
            ...previous, recentLogs: [...previous.recentLogs.filter(item => item.id !== log.id), log].slice(-25),
          } : previous);
        } catch { /* The scheduled snapshot still refreshes malformed events. */ }
        // A burst of granular events shouldn't mean one request each.
        if (refreshTimer.current) return;
        refreshTimer.current = setTimeout(() => {
          refreshTimer.current = null;
          void refresh();
        }, 750);
      });
      es.onerror = () => {
        /* fall back to polling; don't flag offline off a single SSE blip */
      };
    } catch {
      /* SSE unsupported — polling covers it */
    }

    const interval = setInterval(() => void refresh(), pollMs);
    return () => {
      es?.close();
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      clearInterval(interval);
    };
  }, [refresh, pollMs]);

  return { state, loading, connectionError, refresh };
}

/**
 * The backend's real checkpoint sequence, collapsed into the stages a person
 * cares about. Terminal states (SUBMITTED/STAGED/SKIPPED/FAILED) are handled by
 * the caller, not shown as pipeline stages.
 */
export const PIPELINE_STAGES = [
  { id: "open", label: "Page Opened", steps: ["JOB_CLAIMED", "PAGE_OPENED"] },
  { id: "form", label: "Form Parsed", steps: ["FORM_DISCOVERED"] },
  { id: "resume", label: "Resume Uploaded", steps: ["RESUME_UPLOADED"] },
  { id: "answers", label: "Answering Questions", steps: ["PROFILE_FIELDS_FILLED", "QUESTIONS_COMPLETED"] },
  { id: "validate", label: "Validate & Review", steps: ["PRE_SUBMISSION_CHECK"] },
  { id: "submit", label: "Submit", steps: ["SUBMITTING", "VERIFYING_SUBMISSION"] },
] as const;

const STEP_ORDER = [
  "JOB_CLAIMED",
  "PAGE_OPENED",
  "FORM_DISCOVERED",
  "RESUME_UPLOADED",
  "PROFILE_FIELDS_FILLED",
  "QUESTIONS_COMPLETED",
  "PRE_SUBMISSION_CHECK",
  "SUBMITTING",
  "VERIFYING_SUBMISSION",
  "SUBMITTED",
];

/**
 * Map a raw checkpoint step to a pipeline stage index. Returns -1 when the step
 * isn't one we can place — callers then show the stage row as pending rather
 * than guessing a position.
 */
export function stageIndexForStep(step: string | undefined | null): number {
  if (!step) return -1;
  const upper = step.toUpperCase();
  for (let i = 0; i < PIPELINE_STAGES.length; i += 1) {
    if ((PIPELINE_STAGES[i].steps as readonly string[]).includes(upper)) return i;
  }
  return -1;
}

export function stepRank(step: string | undefined | null): number {
  if (!step) return -1;
  return STEP_ORDER.indexOf(step.toUpperCase());
}
