import { getClientApiBaseUrl } from "./api";

function aaBaseUrl(): string {
  return getClientApiBaseUrl();
}

function parseApiError(text: string): string {
  try {
    const data = JSON.parse(text);
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d: { msg?: string }) => d.msg).join(", ");
  } catch {
    /* plain text */
  }
  return text || "Request failed";
}

async function aaFetch<T>(path: string, init?: RequestInit, timeoutMs = 45000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${aaBaseUrl()}/application-assistant${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(parseApiError(text));
    }
    return res.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Save timed out — your answers may still have been saved. Refresh and check.");
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

export interface DiscoveryStartParams {
  careersUrl: string;
  resumeId?: string;
  locationPreferences?: string[];
  workplacePreference?: string;
  minMatchScore?: number;
  includeKeywords?: string[];
  excludeKeywords?: string[];
}

export async function startDiscovery(params: DiscoveryStartParams) {
  return aaFetch<{ success: boolean; run: { id: string } }>("/discovery/start", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function getDiscoveryStatus(runId: string) {
  return aaFetch<{ success: boolean; run: Record<string, unknown> }>(`/discovery/${runId}`);
}

export async function cancelDiscovery(runId: string) {
  return aaFetch<{ success: boolean }>(`/discovery/${runId}/cancel`, { method: "POST" });
}

export async function listJobs(params?: {
  runId?: string;
  minScore?: number;
  include?: string;
  exclude?: string;
  source?: "all" | "scraper" | "discovery";
  q?: string;
  page?: number;
  perPage?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.runId) qs.set("run_id", params.runId);
  if (params?.minScore != null && params.minScore > 0) qs.set("min_score", String(params.minScore));
  if (params?.include) qs.set("include", params.include);
  if (params?.exclude) qs.set("exclude", params.exclude);
  if (params?.source && params.source !== "all") qs.set("source", params.source);
  if (params?.q) qs.set("q", params.q);
  qs.set("page", String(params?.page ?? 1));
  qs.set("per_page", String(params?.perPage ?? 30));
  const query = qs.toString();
  return aaFetch<{
    success: boolean;
    jobs: Record<string, unknown>[];
    total: number;
    page: number;
    perPage: number;
    totalPages: number;
    counts: { all: number; scraper: number; discovery: number };
  }>(`/jobs${query ? `?${query}` : ""}`);
}

export async function importScraperJob(scraperJobId: string) {
  return aaFetch<{
    success: boolean;
    job: Record<string, unknown>;
    match: Record<string, unknown>;
    action?: string;
    created?: boolean;
    updated?: boolean;
    applicationId?: string;
    prepStarted?: boolean;
    prepError?: string;
    queue?: PrepQueueStatus;
  }>(
    "/jobs/import-scraper",
    { method: "POST", body: JSON.stringify({ scraperJobId }) },
  );
}

export async function syncScraperJobs(opts?: { minScore?: number; limit?: number; rescore?: boolean }) {
  const qs = new URLSearchParams();
  if (opts?.minScore != null) qs.set("min_score", String(opts.minScore));
  if (opts?.limit != null) qs.set("limit", String(opts.limit));
  if (opts?.rescore) qs.set("rescore", "true");
  const query = qs.toString();
  return aaFetch<{
    success: boolean;
    processed: number;
    created: number;
    updated: number;
    unchanged: number;
    scraperTotal: number;
    syncedTotal: number;
    lastScrapedAt?: string;
  }>(`/jobs/sync-scraper${query ? `?${query}` : ""}`, { method: "POST" });
}

export async function getScraperSyncStatus() {
  return aaFetch<{
    success: boolean;
    scraperTotal: number;
    syncedTotal: number;
    pendingSync: number;
    lastScrapedAt?: string;
  }>("/jobs/scraper-status");
}

export async function createApplication(jobId: string, resumeId?: string) {
  return aaFetch<{ success: boolean; application: Record<string, unknown> }>("/applications", {
    method: "POST",
    body: JSON.stringify({ jobId, resumeId }),
  });
}

export async function listApplications(
  statusOrOptions?: string | { status?: string; signal?: AbortSignal },
) {
  const options = typeof statusOrOptions === "string" ? { status: statusOrOptions } : (statusOrOptions ?? {});
  const qs = options.status ? `?status=${options.status}` : "";
  return aaFetch<{ success: boolean; applications: Record<string, unknown>[] }>(`/applications${qs}`, {
    signal: options.signal,
  });
}

export type AutofillStateRow = {
  applicationId: string;
  jobId: string;
  companyName?: string;
  roleTitle?: string;
  status?: string;
  hasSavedAutofillState: boolean;
  autofillStepCount: number;
};

export async function listAutofillStates() {
  return aaFetch<{ success: boolean; states: AutofillStateRow[] }>("/applications/autofill-state");
}

export async function prepareApplication(appId: string) {
  return aaFetch<{ success: boolean; application: Record<string, unknown> }>(`/applications/${appId}/prepare`, {
    method: "POST",
  });
}

export async function qwenPrepareJob(jobId: string) {
  return aaFetch<{
    success: boolean;
    applicationId: string;
    application?: Record<string, unknown>;
    status?: string;
    queue?: PrepQueueStatus;
  }>(
    "/qwen/agent/prepare",
    { method: "POST", body: JSON.stringify({ jobId }) },
  );
}

export type PrepQueueStatus = {
  maxConcurrent: number;
  maxQueue: number;
  running: number;
  waiting: number;
  queued: number;
  available: number;
  activeApplicationIds: string[];
  queuedApplicationIds: string[];
  openBrowserCount?: number;
  openBrowserApplicationIds?: string[];
};

export async function getPrepQueueStatus() {
  return aaFetch<{ success: boolean } & PrepQueueStatus>("/qwen/agent/prep-queue");
}

export async function qwenPrepareApplication(appId: string) {
  return aaFetch<{
    success: boolean;
    applicationId: string;
    status?: string;
    queue?: PrepQueueStatus;
  }>(
    "/qwen/agent/prepare",
    { method: "POST", body: JSON.stringify({ applicationId: appId }) },
  );
}

export async function getQwenAgentStatus(appId: string) {
  return aaFetch<{
    success: boolean;
    run: {
      status?: string;
      success?: boolean;
      analysis?: string;
      stoppedReason?: string;
      verifiedCount?: number;
      missingCount?: number;
      companyName?: string;
      roleTitle?: string;
    } | null;
    application: Record<string, unknown> | null;
  }>(`/qwen/agent/status/${appId}`);
}

export type QwenActivityLog = {
  id: string;
  timestamp: string;
  type: string;
  summary: string;
  success: boolean;
  latencyMs?: number;
  error?: string;
  metadata?: Record<string, unknown>;
};

export async function getQwenLogs(limit = 80) {
  return aaFetch<{
    success: boolean;
    logs: QwenActivityLog[];
    activePrep: { active?: boolean; applicationId?: string } | null;
    activeAnalyze: { active?: boolean; applicationId?: string; companyName?: string } | null;
  }>(`/qwen/logs?limit=${limit}`);
}

export async function getQwenLive() {
  return aaFetch<{
    success: boolean;
    activePrep: { active?: boolean; applicationId?: string; step?: string; companyName?: string; roleTitle?: string } | null;
    activeAnalyze: { active?: boolean; applicationId?: string; companyName?: string } | null;
    agentRun: Record<string, unknown> | null;
    logs: { id: string; timestamp: string; type: string; summary: string; success: boolean; metadata?: Record<string, unknown> }[];
    metrics: Record<string, unknown>;
  }>("/qwen/live");
}

export async function getDashboardStats() {
  return aaFetch<{
    success: boolean;
    statusCounts: Record<string, number>;
    totalApplications: number;
    fieldTotals: { verified: number; missing: number; needsReview: number };
    activePrep: { active?: boolean; applicationId?: string; step?: string } | null;
    agentRun: Record<string, unknown> | null;
    recentLogs: { id: string; type: string; summary: string; timestamp: string }[];
    metrics: Record<string, unknown>;
    scraper?: {
      scraperTotal: number;
      syncedTotal: number;
      pendingSync: number;
      lastScrapedAt?: string;
    };
  }>("/dashboard/stats");
}

export async function qwenChat(message: string, context: Record<string, unknown> = {}, history: { role: string; content: string }[] = []) {
  return aaFetch<{ success: boolean; reply: string }>("/qwen/chat", {
    method: "POST",
    body: JSON.stringify({ message, history, context }),
  });
}

export async function openApplicationReview(appId: string, options?: { force?: boolean }) {
  return aaFetch<{
    success: boolean;
    browserOpen?: boolean;
    alreadyOpen?: boolean;
    status?: string;
    message?: string;
    jobUrl?: string;
    pendingFieldCount?: number;
    readyForBrowser?: boolean;
    application?: Record<string, unknown>;
  }>(`/applications/${appId}/open-review`, {
    method: "POST",
    body: JSON.stringify({ force: options?.force ?? false }),
  });
}

export async function closeApplicationBrowser(appId: string) {
  return aaFetch<{ success: boolean; browserOpen: boolean; status?: string }>(
    `/applications/${appId}/stop-browser`,
    { method: "POST" },
  );
}

export async function getReviewStatus(appId: string) {
  return aaFetch<{
    success: boolean;
    status:
      | "idle"
      | "opening"
      | "browser_open"
      | "ready"
      | "failed"
      | "not_found"
      | "profile_incomplete"
      | "submitted"
      | "preparing"
      | "busy";
    browserOpen: boolean;
    submitted?: boolean;
    submittedAt?: string;
    submissionSource?: string;
    readyForBrowser?: boolean;
    pendingFieldCount?: number;
    message: string;
    elapsedSec?: number;
    verifiedCount?: number;
    missingCount?: number;
    progress?: number;
    jobUrl?: string;
  }>(`/applications/${appId}/review-status`);
}

export async function getApplicationReview(appId: string) {
  return aaFetch<{ success: boolean; application: Record<string, unknown>; grouped: Record<string, unknown[]>; summary: Record<string, number> }>(
    `/applications/${appId}/review`,
  );
}

export async function markSubmitted(appId: string) {
  return aaFetch<{ success: boolean; submitted?: boolean; application?: Record<string, unknown> }>(
    `/applications/${appId}/mark-submitted`,
    { method: "POST" },
  );
}

export async function unmarkSubmitted(appId: string) {
  try {
    return await aaFetch<{ success: boolean; submitted?: boolean; application?: Record<string, unknown> }>(
      `/applications/${appId}/unmark-submitted`,
      { method: "POST" },
    );
  } catch {
    // Fallback when API hasn't reloaded unmark route yet — mark-submitted toggles off
    return markSubmitted(appId);
  }
}

export async function archiveApplication(appId: string) {
  return aaFetch<{ success: boolean }>(`/applications/${appId}/archive`, { method: "POST" });
}

export async function getSettings() {
  return aaFetch<{ success: boolean; settings: Record<string, unknown> }>("/settings");
}

export type PendingFieldItem = {
  fieldId: string;
  label: string;
  normalizedKey: string;
  fieldType: string;
  required: boolean;
  options: string[];
  section?: string;
  sensitivityCategory?: string;
  suggestedProfileKey?: string | null;
  storageHint?: string;
  helpText?: string;
  displayTitle?: string;
  displayContext?: string;
  wizardEligible?: boolean;
  category?: "profile" | "application";
  canonicalId?: string;
  variantLabels?: string[];
  applicationCount?: number;
  companyNames?: string[];
  occurrenceCount?: number;
  targets?: {
    appId: string;
    fieldId: string;
    normalizedKey?: string;
    label?: string;
    companyName?: string;
  }[];
};

export type AggregatePendingResponse = {
  success: boolean;
  questions: PendingFieldItem[];
  pending: PendingFieldItem[];
  profilePending: PendingFieldItem[];
  applicationPending: PendingFieldItem[];
  profileKeysMissing: string[];
  count: number;
  rawOccurrenceCount: number;
  applicationCount: number;
  applicationIds: string[];
  applications: { appId: string; companyName: string; roleTitle: string; pendingCount: number }[];
  readyForBrowser: boolean;
};

export async function getAggregatePendingFields(appIds?: string[], opts?: { useAi?: boolean }) {
  const params = new URLSearchParams();
  if (appIds?.length) params.set("app_ids", appIds.join(","));
  if (opts?.useAi) params.set("use_ai", "true");
  const query = params.toString() ? `?${params.toString()}` : "";
  return aaFetch<AggregatePendingResponse>(`/pending-fields/aggregate${query}`);
}

export async function submitUnifiedFieldAnswers(
  answers: {
    canonicalId: string;
    value: string;
    profileKey?: string;
    normalizedKey?: string;
    targets: PendingFieldItem["targets"];
  }[],
) {
  return aaFetch<{
    success: boolean;
    affectedApplicationIds: string[];
    savedTargetCount: number;
    readyApplicationIds: string[];
    repreppedApplicationIds: string[];
  }>("/field-answers/batch", { method: "POST", body: JSON.stringify({ answers }) });
}

export async function getPendingFields(appId: string, opts?: { useAi?: boolean }) {
  const query = opts?.useAi ? "?use_ai=true" : "";
  return aaFetch<{
    success: boolean;
    pending: PendingFieldItem[];
    profilePending: PendingFieldItem[];
    applicationPending: PendingFieldItem[];
    profileKeysMissing: string[];
    count: number;
    readyForBrowser: boolean;
    aiAnalyzed?: boolean;
  }>(`/applications/${appId}/pending-fields${query}`);
}

export async function getApplicationReadiness(appId: string) {
  return aaFetch<{
    success: boolean;
    readyForBrowser: boolean;
    pendingCount: number;
  }>(`/applications/${appId}/readiness`);
}

export async function submitFieldAnswers(
  appId: string,
  answers: { fieldId: string; normalizedKey?: string; value: string; profileKey?: string }[],
) {
  return aaFetch<{
    success: boolean;
    application: Record<string, unknown>;
    savedCount: number;
    readyForBrowser: boolean;
    pendingCount: number;
    aiAnalyzed?: boolean;
    reprepStarted: boolean;
  }>(`/applications/${appId}/field-answers`, { method: "POST", body: JSON.stringify({ answers }) });
}

export async function listProviders() {
  return aaFetch<{ success: boolean; providers: { name: string; supported: boolean }[] }>("/providers");
}
