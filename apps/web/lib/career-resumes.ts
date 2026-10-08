/** Career OS resume versions as seen from a job: which stage of Tailor → Review → Apply → Interview prep it is in. */
export type ResumeApplication = { autopilot_job_id?: string; channel?: string; application_url?: string; source_job_id?: string; submitted_at?: string };
export type ResumeVersionSummary = {
  resume_id: string; label: string; status: "draft" | "approved"; job_id: string; job_url: string; job_title: string; job_company: string;
  created_at: string; approved_at: string | null; pdf_sha256: string | null; blocking: string[]; applications: ResumeApplication[];
};
export type ResumeStage = "tailor" | "review" | "ready" | "applied";

const normalize = (url: string) => url.trim().replace(/[?#].*$/, "").replace(/\/+$/, "").toLowerCase();

export async function fetchResumeVersions(jdId?: string): Promise<ResumeVersionSummary[]> {
  const response = await fetch(`/api/backend/career/resumes${jdId ? `?jd_id=${jdId}` : ""}`, { credentials: "include" });
  if (!response.ok) return [];
  return ((await response.json()) as { versions?: ResumeVersionSummary[] }).versions ?? [];
}

export function stageOf(version: ResumeVersionSummary | undefined): ResumeStage {
  if (!version) return "tailor";
  if (version.applications.length) return "applied";
  return version.status === "approved" ? "ready" : "review";
}

/** The version that represents a job: the one applied with, else the newest approved, else the newest draft. */
export function versionsByJob(versions: ResumeVersionSummary[]): Map<string, ResumeVersionSummary> {
  const rank = (v: ResumeVersionSummary) => (v.applications.length ? 2 : v.status === "approved" ? 1 : 0);
  const out = new Map<string, ResumeVersionSummary>();
  for (const v of versions) {
    const keys = [v.job_url && normalize(v.job_url), ...v.applications.map((a) => a.source_job_id && `id:${a.source_job_id}`)].filter(Boolean) as string[];
    for (const key of keys) {
      const current = out.get(key);
      if (!current || rank(v) > rank(current) || (rank(v) === rank(current) && v.created_at > current.created_at)) out.set(key, v);
    }
  }
  return out;
}

export function versionForJob(map: Map<string, ResumeVersionSummary>, job: { id: string; url?: string }) {
  return map.get(`id:${job.id}`) ?? (job.url ? map.get(normalize(job.url)) : undefined);
}

export function interviewPrepHref(resumeId: string) {
  return `/profile/interview-prep?resume=${encodeURIComponent(resumeId)}`;
}
