export interface DiagnosticService {
  id: string;
  name: string;
  category: string;
  status: "Healthy" | "Degraded" | "Down";
  details: string;
  latencyMs: number;
  updatedAt: string;
}

export interface SystemHealthData {
  overallStatus: "Healthy" | "Degraded" | "Down";
  updatedAt: string;
  services: DiagnosticService[];
}

export interface AutopilotMetricsData {
  period: "1h" | "24h" | "7d";
  jobsDiscovered: number;
  jobsPrepared: number;
  applicationsAttempted: number;
  successfulSubmissions: number;
  submissionSuccessPct: number;
  stagedForReview: number;
  failures: number;
  skipped: number;
  avgApplicationDurationSec: number | null;
  avgResumeTailoringDurationSec: number | null;
  modelFallbackCount: number;
  updatedAt: string;
}

export interface LiveRunTimelineStep {
  stage: string;
  label: string;
  status: "completed" | "running" | "pending" | "failed";
  timestamp: string;
  durationMs: number | null;
  details: string;
}

export interface LiveRunRecord {
  runId: string;
  state: string;
  isActive: boolean;
  targetCount: number;
  processedCount: number;
  submittedCount: number;
  stagedCount: number;
  skippedCount: number;
  failedCount: number;
  currentJob: string;
  workflowStep: string;
  durationSec: number;
  provider: string;
  model: string;
  retries: number;
  startedAt: string;
  completedAt: string | null;
}

export interface RunTimelineResponse {
  runId: string;
  job: {
    id: string;
    company: string;
    title: string;
    status: string;
  };
  timeline: LiveRunTimelineStep[];
}

export interface DiagnosticErrorItem {
  id: string;
  time: string;
  timestamp: string;
  severity: "info" | "warning" | "error" | "critical";
  service: string;
  applicationId: string | null;
  stage: string | null;
  error: string;
  retries: number;
  status: string;
  traceId?: string;
  runId?: string;
  jobId?: string;
  browserSessionId?: string;
  provider?: string;
  model?: string;
  stackTrace?: string;
  playwrightError?: string;
  modelResponseError?: string;
  screenshotPath?: string;
  logs?: string[];
}

export interface SystemAlarmItem {
  id: string;
  alarm: string;
  severity: "warning" | "error" | "critical";
  service: string;
  threshold: string;
  detail: string;
  firstSeen: string;
  lastSeen: string;
  currentStatus: "active" | "acknowledged";
  affectedService: string;
  acknowledged: boolean;
}

async function diagnosticFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api/backend/diagnostic${path}`, {
    ...options,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Diagnostic request failed: ${path}`);
  }
  return res.json();
}

export async function fetchSystemHealth(): Promise<SystemHealthData> {
  return diagnosticFetch<SystemHealthData>("/health");
}

export async function fetchAutopilotMetrics(period: "1h" | "24h" | "7d" = "24h"): Promise<AutopilotMetricsData> {
  return diagnosticFetch<AutopilotMetricsData>(`/metrics?period=${period}`);
}

export async function fetchLiveRuns(): Promise<{ activeRunId: string | null; runs: LiveRunRecord[] }> {
  return diagnosticFetch<{ activeRunId: string | null; runs: LiveRunRecord[] }>("/runs");
}

export async function fetchRunTimeline(runId: string): Promise<RunTimelineResponse> {
  return diagnosticFetch<RunTimelineResponse>(`/runs/${encodeURIComponent(runId)}/timeline`);
}

export async function fetchDiagnosticErrors(params?: {
  severity?: string;
  service?: string;
  search?: string;
}): Promise<{ total: number; errors: DiagnosticErrorItem[] }> {
  const searchParams = new URLSearchParams();
  if (params?.severity) searchParams.set("severity", params.severity);
  if (params?.service) searchParams.set("service", params.service);
  if (params?.search) searchParams.set("search", params.search);
  return diagnosticFetch<{ total: number; errors: DiagnosticErrorItem[] }>(`/errors?${searchParams.toString()}`);
}

export async function fetchSystemAlarms(): Promise<{ total: number; alarms: SystemAlarmItem[] }> {
  return diagnosticFetch<{ total: number; alarms: SystemAlarmItem[] }>("/alarms");
}

export async function acknowledgeSystemAlarm(alarmId: string): Promise<{ success: boolean }> {
  return diagnosticFetch<{ success: boolean }>(`/alarms/${encodeURIComponent(alarmId)}/ack`, {
    method: "POST",
    body: JSON.stringify({ acknowledged: true }),
  });
}

export type MetricBucket = {timestamp:string;submitted:number;failed:number;review:number;skipped:number;other:number;durationSec:number|null;samples:number};
export type DiagnosticSeries = {period:string;bucketSeconds:number;buckets:MetricBucket[];updatedAt:string;basis:string};
export const fetchDiagnosticSeries = (period:string) => diagnosticFetch<DiagnosticSeries>(`/series?period=${period}`);

export type OutcomeKind = "SUBMITTED" | "STAGED" | "FAILED" | "SKIPPED";

export interface OutcomeReasonCount {
  reason: string;
  count: number;
  exampleUrl: string;
}

export interface OutcomeFieldCount {
  field: string;
  count: number;
}

export interface OutcomeEvent {
  timestamp: string;
  jobId: string;
  company: string;
  title: string;
  outcome: OutcomeKind;
  currentStatus: string;
  reason: string;
  detail: string;
  matchScore: number | null;
  applicationUrl: string;
  /** Seconds from this attempt's JOB_CLAIMED to its outcome; null when it cannot be timed. */
  durationSec: number | null;
  synthetic: boolean;
}

export interface DurationStats {
  count: number;
  avgSec: number | null;
  medianSec: number | null;
  p90Sec: number | null;
  maxSec: number | null;
  totalSec: number;
}

export type OutcomeSeriesBucket = { bucket: string } & Record<OutcomeKind, number>;

export interface OutcomesReport {
  period: string;
  hours: number;
  maxDays: number;
  windowStart: string;
  windowEnd: string;
  bucketUnit: "hour" | "day";
  updatedAt: string;
  allTimeStatusCounts: Record<string, number>;
  windowOutcomeCounts: Record<OutcomeKind, number>;
  windowJobsTouched: number;
  windowCurrentStatusCounts: Record<string, number>;
  windowReasons: Record<"STAGED" | "FAILED" | "SKIPPED", OutcomeReasonCount[]>;
  currentStatusReasons: Record<"MANUAL_REVIEW" | "NEEDS_REVIEW" | "FAILED" | "INELIGIBLE", OutcomeReasonCount[]>;
  topBlankFields: OutcomeFieldCount[];
  series: OutcomeSeriesBucket[];
  durationStats: Record<"ALL" | OutcomeKind, DurationStats>;
  slowestEvents: OutcomeEvent[];
  events: OutcomeEvent[];
  eventsTotal: number;
  eventsTruncated: boolean;
}

/** `period` is a number plus "h" or "d", up to 30 days (e.g. "12h", "7d", "30d"). */
export async function fetchOutcomesReport(period = "12h"): Promise<OutcomesReport> {
  return diagnosticFetch<OutcomesReport>(`/outcomes?period=${encodeURIComponent(period)}`);
}
