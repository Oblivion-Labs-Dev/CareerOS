/** Zero-token inbox triage helpers (career-ops inbox.ts pattern). */

export type AtsSource = "greenhouse" | "lever" | "ashby" | "workday" | "other";

export type Seniority = "lead" | "staff" | "senior" | "mid" | "junior" | "intern";

export const SENIORITY_ORDER: Seniority[] = ["lead", "staff", "senior", "mid", "junior", "intern"];

export const SENIORITY_LABEL: Record<Seniority, string> = {
  lead: "Lead",
  staff: "Staff+",
  senior: "Senior",
  mid: "Mid",
  junior: "Junior",
  intern: "Intern",
};

export const ATS_LABEL: Record<AtsSource, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workday: "Workday",
  other: "Other",
};

function domainIs(host: string, base: string) {
  return host === base || host.endsWith(`.${base}`);
}

export function sourceFromUrl(url: string): AtsSource {
  try {
    const host = new URL(url).hostname.toLowerCase();
    if (domainIs(host, "greenhouse.io")) return "greenhouse";
    if (domainIs(host, "lever.co")) return "lever";
    if (domainIs(host, "ashbyhq.com")) return "ashby";
    if (domainIs(host, "myworkdayjobs.com") || domainIs(host, "workday.com")) return "workday";
  } catch {
    return "other";
  }
  return "other";
}

export function seniorityFromTitle(title: string): Seniority | null {
  const t = ` ${title.toLowerCase()} `;
  if (/\b(head|vp|vice president|director|chief|manager|mgr|lead)\b/.test(t)) return "lead";
  if (/\b(staff|principal|distinguished|fellow|architect)\b/.test(t)) return "staff";
  if (/\b(senior|sr\.?|snr)\b/.test(t)) return "senior";
  if (/\b(junior|jr\.?|entry|graduate|associate)\b/.test(t)) return "junior";
  if (/\b(intern|internship|working student|apprentice)\b/.test(t)) return "intern";
  if (/\b(engineer|developer|scientist|designer|analyst|specialist|consultant)\b/.test(t)) return "mid";
  return null;
}

export function freshnessDaysFromJob(updatedAt?: string, scrapedAt?: string): number | null {
  const raw = updatedAt || scrapedAt;
  if (!raw) return null;
  const time = Date.parse(raw);
  if (Number.isNaN(time)) return null;
  return Math.floor((Date.now() - time) / 86_400_000);
}

export type TriageJob = {
  id: string;
  title: string;
  url: string;
  updatedAt?: string;
  scrapedAt?: string;
};

export function triageSignals(job: TriageJob) {
  return {
    ats: sourceFromUrl(job.url),
    seniority: seniorityFromTitle(job.title),
    freshnessDays: freshnessDaysFromJob(job.updatedAt, job.scrapedAt),
  };
}

export type TriageFilters = {
  ats?: AtsSource | "all";
  seniority?: Seniority | "all";
  maxAgeDays?: number | "all";
};

export function matchesTriageFilters(job: TriageJob, filters: TriageFilters): boolean {
  const signals = triageSignals(job);
  if (filters.ats && filters.ats !== "all" && signals.ats !== filters.ats) return false;
  if (filters.seniority && filters.seniority !== "all" && signals.seniority !== filters.seniority) return false;
  if (filters.maxAgeDays && filters.maxAgeDays !== "all") {
    if (signals.freshnessDays == null || signals.freshnessDays > filters.maxAgeDays) return false;
  }
  return true;
}
