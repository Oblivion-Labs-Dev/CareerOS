import { getClientApiBaseUrl, postJson } from "./api";
import type { StoredResume } from "./documents-api";

export type ResumeProfile = {
  id: string;
  name: string;
  isDefault: boolean;
  resume: StoredResume | null;
  createdAt?: string;
  updatedAt?: string;
};

export type AtsChecklistItem = { label: string; passed: boolean; detail: string };
export type AtsScore = { score: number; checklist: AtsChecklistItem[]; wordCount?: number };

export type TailoringMode = "off" | "honest" | "aggressive";

export type TailoredBullet = {
  id: string;
  company: string;
  role: string;
  project: string;
  original: string;
  tailored: string;
  changed: boolean;
};

export type TailoringResult = {
  mode: TailoringMode;
  bullets: TailoredBullet[];
  skillsList: string[];
  atsMatchScore: number | null;
  overallCritique: string;
};

export async function listResumeProfiles(): Promise<ResumeProfile[]> {
  const res = await fetch(`${getClientApiBaseUrl()}/profile/resume-profiles`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load resume profiles");
  const data = (await res.json()) as { profiles: ResumeProfile[] };
  return data.profiles ?? [];
}

export async function createResumeProfile(name: string, resume?: StoredResume | null): Promise<ResumeProfile> {
  const res = await postJson<{ success: boolean; profile: ResumeProfile }>("/profile/resume-profiles", { name, resume });
  return res.profile;
}

export async function patchResumeProfile(id: string, patch: Partial<Pick<ResumeProfile, "name" | "resume">>): Promise<ResumeProfile> {
  const res = await postJson<{ success: boolean; profile: ResumeProfile }>(`/profile/resume-profiles/${id}`, patch, "PATCH");
  return res.profile;
}

export async function deleteResumeProfile(id: string): Promise<void> {
  await postJson(`/profile/resume-profiles/${id}`, {}, "DELETE");
}

export async function setDefaultResumeProfile(id: string): Promise<ResumeProfile> {
  const res = await postJson<{ success: boolean; profile: ResumeProfile }>(`/profile/resume-profiles/${id}/set-default`, {});
  return res.profile;
}

export async function fetchAtsScore(profileId?: string, jobId?: string): Promise<AtsScore> {
  const params = new URLSearchParams();
  if (profileId) params.set("profileId", profileId);
  if (jobId) params.set("jobId", jobId);
  const res = await fetch(`${getClientApiBaseUrl()}/resume/ats-score?${params.toString()}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load ATS score");
  return res.json();
}

export async function fetchTailoringMode(): Promise<TailoringMode> {
  const res = await fetch(`${getClientApiBaseUrl()}/application-assistant/settings`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load tailoring settings");
  const data = (await res.json()) as { settings?: { tailoringMode?: TailoringMode } };
  return data.settings?.tailoringMode ?? "off";
}

export async function setTailoringMode(mode: TailoringMode): Promise<TailoringMode> {
  const res = await postJson<{ settings?: { tailoringMode?: TailoringMode } }>("/application-assistant/settings", { tailoringMode: mode });
  return res.settings?.tailoringMode ?? mode;
}

export async function tailorResumeForJob(input: {
  accomplishmentIds?: string[];
  jobId?: string;
  targetCompany?: string;
  targetRole?: string;
  jobDescription?: string;
  mode?: TailoringMode;
}): Promise<TailoringResult> {
  const res = await postJson<{ success: boolean; result: TailoringResult }>("/resume/tailor", input);
  return res.result;
}

export async function approveResumeTailoring(input: {
  mode: TailoringMode;
  jobId?: string;
  targetCompany?: string;
  targetRole?: string;
  bullets: TailoredBullet[];
  skillsList: string[];
}): Promise<void> {
  await postJson("/resume/tailor/approve", input);
}
