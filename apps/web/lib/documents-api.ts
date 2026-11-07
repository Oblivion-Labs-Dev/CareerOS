import { getClientApiBaseUrl, postJson } from "./api";
import { fileToBase64 } from "./resume-intelligence-api";

export type StoredResume = {
  id?: string;
  name?: string;
  type?: string;
  mimeType?: string;
  base64?: string;
  parsedText?: string;
  updatedAt?: string;
};

export async function fetchDefaultResume(): Promise<StoredResume | null> {
  const res = await fetch(`${getClientApiBaseUrl()}/documents/resume`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to load resume");
  const data = (await res.json()) as { resume?: StoredResume | null };
  return data.resume ?? null;
}

export async function uploadDefaultResume(file: File): Promise<StoredResume> {
  const { base64, mimeType, filename } = await fileToBase64(file);
  const res = await postJson<{ success: boolean; resume: StoredResume }>("/documents/resume", {
    resume: {
      name: filename,
      type: mimeType,
      mimeType,
      base64,
    },
  });
  return res.resume;
}

/** Whether the job-match profile could be rebuilt from this resume. */
export type MatchProfileStatus = { ok: true; path: string } | { ok: false; error: string };

export function matchProfileProblem(status: MatchProfileStatus | undefined): string {
  return status && !status.ok ? `Job matching could not read your skills from this resume (${status.error}), so jobs are ranked without them.` : "";
}

export async function parseResumeIntoProfile(force = false): Promise<{ profile: Record<string, unknown>; extracted: Record<string, unknown>; matchProfile?: MatchProfileStatus }> {
  return postJson("/api/parse-resume", { force });
}
