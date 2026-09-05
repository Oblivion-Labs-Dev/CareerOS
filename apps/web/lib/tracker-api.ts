/** Tracker: Inbox (classified recruiter email) + Pipeline (Kanban) API client. */

function trackerBaseUrl(): string {
  // Keep tracker traffic on the dashboard origin — the route handler forwards it to the
  // local API, avoiding browser CORS and localhost/IP mismatches (same pattern as
  // application-assistant-api.ts).
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

async function trackerFetch<T>(path: string, init?: RequestInit, timeoutMs = 45000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${trackerBaseUrl()}${path}`, {
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

export type PipelineColumnKey = "applied" | "ghosted" | "interviewing" | "rejected" | "offer";

export type PipelineItem = {
  id: string;
  companyName: string;
  roleTitle: string;
  status: string;
  daysInStage: number | null;
  url?: string;
  updatedAt?: string;
};

export type PipelineColumn = {
  key: PipelineColumnKey;
  label: string;
  items: PipelineItem[];
};

export type PipelineResponse = {
  columns: PipelineColumn[];
  funnel: { key: PipelineColumnKey; label: string; count: number }[];
  total: number;
  ghostThresholdDays: number;
};

export function getTrackerPipeline(): Promise<PipelineResponse> {
  return trackerFetch<PipelineResponse>("/tracker/pipeline");
}

export type EmailCategory =
  | "offer"
  | "rejection"
  | "assessment"
  | "interview"
  | "verification"
  | "reminder"
  | "applied"
  | "uncategorized";

export type ClassifiedThread = {
  uid: string;
  subject: string;
  fromName: string;
  fromAddress: string;
  date: string;
  snippet?: string;
  category: EmailCategory;
  categoryLabel: string;
  confidence: number;
};

export type ClassifiedThreadsResponse = {
  success: boolean;
  threads: ClassifiedThread[];
  count: number;
  categoryCounts: Record<string, number>;
};

export function listClassifiedRecruiterThreads(limit = 20): Promise<ClassifiedThreadsResponse> {
  return trackerFetch<ClassifiedThreadsResponse>(`/email/recruiter-threads/classified?limit=${limit}`, undefined, 60000);
}

export async function downloadApplicationsCsv(): Promise<void> {
  const res = await fetch(`${trackerBaseUrl()}/applications/export.csv`, { cache: "no-store" });
  if (!res.ok) throw new Error(parseApiError(await res.text()));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "careeros-applications.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export type ImportApplicationsResult = { success: boolean; created: number; updated: number; skipped: number };

export async function importApplicationsCsv(file: File): Promise<ImportApplicationsResult> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${trackerBaseUrl()}/applications/import`, { method: "POST", body: formData, cache: "no-store" });
  if (!res.ok) throw new Error(parseApiError(await res.text()));
  return res.json();
}
