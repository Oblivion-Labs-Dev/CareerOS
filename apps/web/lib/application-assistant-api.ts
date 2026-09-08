function aaBaseUrl(): string {
  // Keep application-assistant traffic on the dashboard origin. The route handler
  // forwards it to the local API, avoiding browser CORS and localhost/IP mismatches.
  return "/api/backend";
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
      throw new Error(`Request to ${path} timed out after ${Math.round(timeoutMs / 1000)}s. Please refresh or retry.`);
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

export async function generateFreeformAnswer(question: string, company?: string, role?: string, jobDescription?: string) {
  return aaFetch<{ success: boolean; answer: string; reasoning?: string }>("/generate-answer", {
    method: "POST",
    body: JSON.stringify({ question, company, role, jobDescription }),
  });
}

// ── Autopilot Autonomous Runner API Helpers ───────────────────────────────────

export async function startAutopilot(options?: Record<string, any>) {
  return aaFetch<{ success: boolean; run: any }>("/autopilot/start", {
    method: "POST",
    body: JSON.stringify(options || {}),
  });
}

export async function pauseAutopilot() {
  return aaFetch<{ success: boolean; run: any }>("/autopilot/pause", {
    method: "POST",
  });
}

export async function stopAutopilot() {
  return aaFetch<{ success: boolean; run: any }>("/autopilot/stop", {
    method: "POST",
  });
}

export async function getAutopilotStatus() {
  return aaFetch<{
    running: boolean;
    status: string;
    run: any;
    activeJob: any;
    queueSize: number;
    recentLogs: Array<{ id: string; timestamp: string; level: string; message: string; metadata?: any }>;
    workers?: Array<{
      workerId: string;
      slot: number;
      status: string;
      currentJob: { id: string; company: string; title: string } | null;
      currentStep: string;
      startedAt: string;
      error: string;
      jobsCompleted: number;
      jobsFailed: number;
    }>;
    concurrency?: number;
    concurrencyMetrics?: {
      activeWorkers: number;
      totalWorkers: number;
      avgJobTimeSec: number;
      throughputPerMin: number;
      lockContentionCount: number;
      selfHealingRoundsCompleted: number;
      totalJobsStarted: number;
      totalJobsFinished: number;
    };
    selfHealing?: {
      status: string;
      currentRound: number;
      maxRounds: number;
      lastPatchSummary: string;
      patchesApplied: number;
      lastError: string;
      patchHistory: any[];
    };
    // Lifetime counters the backend already returns; the dashboard activity
    // card reads these to draw its status breakdown.
    cumulative?: {
      submitted?: number;
      staged?: number;
      skipped?: number;
      failed?: number;
      processed?: number;
      queueRemaining?: number;
    };
  }>("/autopilot/status");
}

export function getAutopilotEventSource(): EventSource {
  return new EventSource(`${aaBaseUrl()}/application-assistant/autopilot/events`);
}

export async function getAutopilotJobs(status?: string, limit = 200) {
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  qs.set("limit", String(limit));
  return aaFetch<{ success: boolean; jobs: any[]; count: number }>(`/autopilot/jobs?${qs.toString()}`);
}

export interface AutopilotJobsPageParams {
  status?: string; // comma-separated, e.g. "QUEUED,NEEDS_REVIEW,STAGED"
  role?: string;
  location?: string;
  company?: string;
  sortBy?: "matchScore" | "submittedAt" | "updatedAt";
  sortDir?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export async function getAutopilotJobsPage(params: AutopilotJobsPageParams) {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.role) qs.set("role", params.role);
  if (params.location) qs.set("location", params.location);
  if (params.company) qs.set("company", params.company);
  if (params.sortBy) qs.set("sortBy", params.sortBy);
  if (params.sortDir) qs.set("sortDir", params.sortDir);
  qs.set("limit", String(params.limit ?? 24));
  qs.set("offset", String(params.offset ?? 0));
  return aaFetch<{ success: boolean; jobs: any[]; count: number; total: number; hasMore: boolean }>(
    `/autopilot/jobs?${qs.toString()}`
  );
}

export async function deleteAutopilotJob(jobId: string) {
  return aaFetch<{ success: boolean; deletedId: string; message: string }>(`/autopilot/jobs/${jobId}`, {
    method: "DELETE",
  });
}

export async function getStagedApplications() {
  return aaFetch<{ staged: any[]; count: number }>("/autopilot/staged");
}

export async function approveStagedAnswer(id: string, question: string, answer: string) {
  return aaFetch<{ success: boolean; job: any }>(`/autopilot/staged/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ question, answer }),
  });
}

export async function skipStagedApplication(id: string, reason?: string) {
  return aaFetch<{ success: boolean; job: any }>(`/autopilot/staged/${id}/skip`, {
    method: "POST",
    body: JSON.stringify({ reason: reason || "" }),
  });
}

export async function classifyPendingQuestions(id: string) {
  return aaFetch<{ success: boolean; pendingQuestions: { question: string; category: string; fieldType?: string; options?: string[] }[] }>(
    `/autopilot/jobs/${id}/classify-questions`,
    { method: "POST" }
  );
}

export async function enqueueJobForAutopilot(job: Record<string, any>) {
  return aaFetch<{ success: boolean; job: any }>("/autopilot/enqueue", {
    method: "POST",
    body: JSON.stringify(job),
  });
}

export async function resetSubmittedAutopilotJobs(status?: string) {
  return aaFetch<{ success: boolean; resetCount: number; message: string }>("/autopilot/reset-submitted", {
    method: "POST",
    body: JSON.stringify({ status: status || "ALL" }),
  });
}

export async function resetSingleAutopilotJob(id: string) {
  return aaFetch<{ success: boolean; id: string; message: string }>(`/autopilot/jobs/${id}/reset`, {
    method: "POST",
  });
}

export async function reprocessFailedAutopilotJobs() {
  return aaFetch<{ success: boolean; reprocessedCount: number; message: string; run?: any }>("/autopilot/reprocess-failed", {
    method: "POST",
  });
}

export async function reprocessStagedAutopilotJobs() {
  return aaFetch<{ success: boolean; reprocessedCount: number; message: string; run?: any }>("/autopilot/reprocess-staged", {
    method: "POST",
  });
}

export async function reprocessSkippedAutopilotJobs() {
  return aaFetch<{ success: boolean; reprocessedCount: number; message: string; run?: any }>("/autopilot/reprocess-skipped", {
    method: "POST",
  });
}

export async function reprocessSingleAutopilotJob(id: string) {
  return aaFetch<{ success: boolean; id: string; message: string; run?: any }>(`/autopilot/jobs/${id}/reprocess`, {
    method: "POST",
  });
}

export async function getAutopilotWorkers() {
  return aaFetch<{
    success: boolean;
    workers: Array<{
      workerId: string;
      slot: number;
      status: string;
      currentJob: { id: string; company: string; title: string } | null;
      currentStep: string;
      startedAt: string;
      error: string;
      jobsCompleted: number;
      jobsFailed: number;
    }>;
    concurrency: number;
    activeWorkers: number;
    concurrencyMetrics: any;
  }>("/autopilot/workers");
}

export async function triggerSelfHeal() {
  return aaFetch<{
    success: boolean;
    totalRounds?: number;
    patchesApplied?: number;
    lastPatchSummary?: string;
    rounds?: any[];
    autopilotRestarted?: boolean;
    run?: any;
    message?: string;
  }>("/autopilot/self-heal", { method: "POST" });
}

export async function getSelfHealingLog() {
  return aaFetch<{
    success: boolean;
    status: string;
    currentRound: number;
    maxRounds: number;
    lastPatchSummary: string;
    patchesApplied: number;
    lastError: string;
    patchHistory: any[];
  }>("/autopilot/self-healing-log");
}


export async function createApplication(jobId: string, resumeId?: string) {
  return aaFetch<{ success: boolean; application: Record<string, unknown> }>("/applications", {
    method: "POST",
    body: JSON.stringify({ jobId, resumeId }),
  });
}

export type QuickAddJobInput = {
  url: string;
  title?: string;
  company?: string;
  location?: string;
  description?: string;
  resumeId?: string;
};

export async function quickAddApplication(input: QuickAddJobInput) {
  return aaFetch<{
    success: boolean;
    job: Record<string, unknown>;
    application: Record<string, unknown>;
    autoExtracted: boolean;
  }>("/applications/quick-add", {
    method: "POST",
    body: JSON.stringify(input),
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

export async function unarchiveApplication(appId: string) {
  return aaFetch<{ success: boolean }>(`/applications/${appId}/unarchive`, { method: "POST" });
}

export async function getSettings() {
  return aaFetch<{ success: boolean; settings: Record<string, any> }>("/settings");
}

export async function updateSettings(settings: Record<string, any>) {
  return aaFetch<{ success: boolean; settings: Record<string, any> }>("/settings", {
    method: "POST",
    body: JSON.stringify(settings),
  });
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
  applications: { appId: string; companyName: string; roleTitle: string; pendingCount: number; readyForBrowser?: boolean }[];
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

// ─── TSENTA SUITE: VISUAL DIFFS, RECEIPTS & PRE-FLIGHT APPROVAL ───

export interface BulletDiffChunk {
  type: "eq" | "add" | "del";
  text: string;
}

export interface BulletDiffItem {
  index: number;
  original: string;
  tailored: string;
  isModified: boolean;
  chunks: BulletDiffChunk[];
}

export interface TailorDiffResponse {
  jobId: string;
  company: string;
  title: string;
  mode?: "off" | "honest" | "aggressive";
  matchScore: number;
  salaryRange: string;
  visaStatus: string;
  bulletDiffs: BulletDiffItem[];
  tailoredCoverLetter: string;
  screeningQAs: { question: string; suggestedAnswer: string; confidence: number }[];
  totalChanges: number;
}

export interface SubmissionReceiptItem {
  receiptId: string;
  jobId: string;
  company: string;
  title: string;
  applicationUrl: string;
  confirmationUrl: string;
  confirmationText: string;
  submittedAt: string;
  fieldsFilled: Record<string, string>;
  fieldsCount: number;
  presubmitScreenshot?: string;
  confirmationScreenshot?: string;
  verificationStatus: string;
  certificateFingerprint: string;
  tailoringMode?: "off" | "honest" | "aggressive" | null;
  resumeFileUsed?: string | null;
  matchScoreAtSubmission?: number | null;
}

export async function getJobTailorDiff(jobId: string, mode?: "off" | "honest" | "aggressive") {
  const query = mode ? `?mode=${encodeURIComponent(mode)}` : "";
  return aaFetch<{ success: boolean; diff: TailorDiffResponse }>(`/jobs/${jobId}/tailor-diff${query}`);
}

export async function approvePreflightSubmission(
  jobId: string,
  customAnswers?: Record<string, string>,
  tailoringMode?: "off" | "honest" | "aggressive",
) {
  return aaFetch<{ success: boolean; message: string; job: any; run: any }>(`/jobs/${jobId}/preflight-approve`, {
    method: "POST",
    body: JSON.stringify({ customAnswers, tailoringMode }),
  });
}

export async function getSubmissionReceipt(id: string) {
  return aaFetch<{ success: boolean; receipt: SubmissionReceiptItem }>(`/receipts/${id}`);
}

export async function listSubmissionReceipts() {
  return aaFetch<{ success: boolean; receipts: SubmissionReceiptItem[]; total: number }>("/receipts");
}

export async function syncInboundEmail(payload: { sender: string; subject: string; body: string }) {
  return aaFetch<{ success: boolean; record: any }>("/email-sync", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function auditSponsorshipApplications() {
  return aaFetch<{
    success: boolean;
    auditedTotal: number;
    skippedCount: number;
    skippedJobs: { id: string; company: string; title: string; reason: string }[];
    message: string;
  }>("/autopilot/audit-sponsorship", {
    method: "POST",
  });
}

export async function resetAutopilotQueue() {
  return aaFetch<{ success: boolean; resetCount: number; resetJobsCount?: number; message: string }>("/autopilot/reset-submitted", {
    method: "POST",
    body: JSON.stringify({ status: "ALL" }),
  });
}

export function getTailoredResumePdfUrl(jobId: string, mode?: "off" | "honest" | "aggressive"): string {
  const modeParam = mode ? `?mode=${mode}` : "";
  return `${aaBaseUrl()}/application-assistant/jobs/${jobId}/tailor-resume-pdf${modeParam}`;
}



