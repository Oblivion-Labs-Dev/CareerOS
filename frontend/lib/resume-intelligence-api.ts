import { getClientApiBaseUrl } from "./api";

const BASE = getClientApiBaseUrl();

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

async function riFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/resume-intelligence${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseApiError(text));
  }
  return res.json();
}

export type RiPerson = {
  id: string;
  fullName: string;
  email?: string;
  notes?: string;
  createdAt?: string;
};

export type RiScan = {
  id: string;
  personId: string;
  status: string;
  textPreview?: string;
  contact?: Record<string, string>;
  skills?: string[];
  workHistory?: { company?: string; title?: string; dates?: string; highlights?: string[] }[];
  accomplishmentCandidates?: {
    tempId?: string;
    id?: string;
    title?: string;
    company?: string;
    bullet?: string;
    technologies?: string[];
    confidence?: number;
  }[];
  atsKeywordSets?: Record<string, string[]>;
  qwenUsed?: boolean;
  qwenError?: string;
};

export type RiMatchResult = {
  overallScore: number;
  callLikelihood: string;
  summary: string;
  explicit: { term: string; coverage: string }[];
  inferred: { term: string; coverage: string }[];
  unsupported: { term: string; coverage: string }[];
  missing: { term: string; coverage: string }[];
  relevantAccomplishments: { recordId: string; title: string; company: string; hits: number }[];
  atsKeywordSets: {
    primary?: string[];
    matchedSkills?: string[];
    gapSkills?: string[];
    requiredPhrases?: string[];
  };
};

export type RiRecommendations = {
  callLikelihoodSummary?: string;
  topGaps?: string[];
  addToResume?: string[];
  emphasizeAccomplishments?: string[];
  suggestedBullets?: string[];
  keywordPhrasesToAdd?: string[];
};

export type RiGraph = {
  nodes: { id: string; label: string; type: string; x: number; y: number; recordId?: string }[];
  links: { source: string; target: string; label?: string }[];
  stats: { accomplishmentCount: number; nodeCount: number; edgeCount: number };
};

export async function getQwenStatus() {
  return riFetch<{ success: boolean; enabled: boolean; model: string; connection: { success: boolean } }>("/qwen/status");
}

export async function listPeople() {
  return riFetch<{ success: boolean; people: RiPerson[] }>("/people");
}

export async function createPerson(fullName: string, email = "", notes = "") {
  return riFetch<{ success: boolean; person: RiPerson }>("/people", {
    method: "POST",
    body: JSON.stringify({ fullName, email, notes }),
  });
}

export async function scanResume(params: {
  personId?: string;
  personName?: string;
  text?: string;
  base64?: string;
  mimeType?: string;
  filename?: string;
  useQwen?: boolean;
}) {
  return riFetch<{ success: boolean; scan: RiScan; personId: string }>("/scan", {
    method: "POST",
    body: JSON.stringify({
      personId: params.personId || "",
      personName: params.personName || "",
      text: params.text || "",
      base64: params.base64 || "",
      mimeType: params.mimeType || "",
      filename: params.filename || "",
      useQwen: params.useQwen !== false,
    }),
  });
}

export async function commitScan(scanId: string, candidateIds?: string[]) {
  return riFetch<{ success: boolean; count: number }>(`/scans/${scanId}/commit`, {
    method: "POST",
    body: JSON.stringify({ candidateIds: candidateIds || [] }),
  });
}

export async function matchJob(params: {
  jobDescription: string;
  jobTitle?: string;
  personId?: string;
  resumeText?: string;
  useQwen?: boolean;
}) {
  return riFetch<{
    success: boolean;
    matchId: string;
    match: RiMatchResult;
    recommendations: RiRecommendations | null;
    qwenAts: Record<string, unknown> | null;
  }>("/match", {
    method: "POST",
    body: JSON.stringify({
      jobDescription: params.jobDescription,
      jobTitle: params.jobTitle || "",
      personId: params.personId || "",
      resumeText: params.resumeText || "",
      useQwen: params.useQwen !== false,
      includeRecommendations: true,
    }),
  });
}

export async function getKnowledgeGraph(personId?: string) {
  const q = personId ? `?personId=${encodeURIComponent(personId)}` : "";
  return riFetch<{ success: boolean; graph: RiGraph; accomplishmentCount: number }>(`/graph${q}`);
}

export async function listScans(personId?: string) {
  const q = personId ? `?personId=${encodeURIComponent(personId)}` : "";
  return riFetch<{ success: boolean; scans: RiScan[] }>(`/scans${q}`);
}

export function fileToBase64(file: File): Promise<{ base64: string; mimeType: string; filename: string }> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const base64 = result.includes(",") ? result.split(",")[1] : result;
      resolve({ base64, mimeType: file.type, filename: file.name });
    };
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}
