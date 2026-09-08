import type { AutopilotJobRow } from "./job-types";

export type StatusFilter = "all" | "submitted" | "review" | "failed" | "skipped" | "queued" | "ineligible";

export type SortMode = "priority" | "match" | "recent" | "company";

export const FILTERS: { id: StatusFilter; label: string; match: (j: AutopilotJobRow) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "submitted", label: "Submitted", match: (j) => j.status === "SUBMITTED" },
  { id: "review", label: "Review", match: (j) => j.status === "NEEDS_REVIEW" || j.status === "STAGED" },
  { id: "failed", label: "Failed", match: (j) => j.status === "FAILED" },
  { id: "skipped", label: "Skipped", match: (j) => j.status === "SKIPPED" },
  { id: "queued", label: "Queued", match: (j) => j.status === "QUEUED" || j.status === "APPLYING" },
  // Ineligible is deliberately its own bucket, not folded into Skipped:
  // these can never be applied to (citizenship, sponsorship, non-US, dead
  // posting), so mixing them into a queue the user is meant to work through
  // is what made that queue useless to review.
  { id: "ineligible", label: "Ineligible", match: (j) => j.status === "INELIGIBLE" },
];

export const SORTS: { id: SortMode; label: string }[] = [
  { id: "priority", label: "Priority (Senior + Seattle)" },
  { id: "match", label: "Match score" },
  { id: "recent", label: "Most recent" },
  { id: "company", label: "Company A-Z" },
];

/** Mirrors role_location_priority_bonus in the API's job_filter_ranker, so the
 *  order shown here is the order Autopilot actually applies in: Senior-level
 *  roles ahead of Staff/Principal, Seattle ahead of the rest of the US. */
export function priorityRank(j: AutopilotJobRow): number {
  const t = String(j.title || "").toLowerCase();
  const loc = String(j.location || "").toLowerCase();
  let score = Number(j.matchScore || 0);
  const aboveSenior = ["staff", "principal", "distinguished", "fellow",
    "architect", "director", "head of", "vp ", "vice president"].some((k) => t.includes(k));
  const isSenior = ["senior software engineer", "sr. software engineer",
    "sr software engineer", "senior swe"].some((k) => t.includes(k));
  if (isSenior && !aboveSenior) score += 40;
  else if (aboveSenior) score -= 40;
  else if (t.includes("senior") && t.includes("software engineer")) score += 30;
  else if (t.includes("software engineer") || t.includes("software developer")) score += 10;
  if (["seattle", "bellevue", "redmond", "kirkland", ", wa", "washington"]
      .some((k) => loc.includes(k))) score += 25;
  return score;
}

/** Card accent + label, driven only by the backend's real status value. */
export const INELIGIBILITY_LABELS: Record<string, string> = {
  REQUIRES_US_CITIZENSHIP: "Requires U.S. citizenship / clearance",
  NO_VISA_SPONSORSHIP: "Does not sponsor visas",
  OUTSIDE_UNITED_STATES: "Outside the United States",
  POSTING_EXPIRED: "Posting expired or was removed",
  NOT_A_REAL_POSTING: "Not a real posting",
  DUPLICATE_APPLICATION: "Already applied",
};

export function statusView(status: string | undefined): { key: string; label: string } {
  switch (status) {
    case "SUBMITTED": return { key: "submitted", label: "Submitted" };
    case "NEEDS_REVIEW":
    case "STAGED": return { key: "review", label: "In review" };
    case "FAILED": return { key: "failed", label: "Failed" };
    case "SKIPPED": return { key: "skipped", label: "Skipped" };
    case "APPLYING": return { key: "applying", label: "Applying" };
    case "INELIGIBLE": return { key: "ineligible", label: "Ineligible" };
    default: return { key: "queued", label: "Queued" };
  }
}

/** CareerOS match bands. Score is absent on some rows — we show nothing rather than guess. */
export function matchBand(score: number): { band: string; label: string } {
  if (score >= 90) return { band: "excellent", label: "Excellent match" };
  if (score >= 80) return { band: "strong", label: "Strong match" };
  if (score >= 70) return { band: "good", label: "Good match" };
  return { band: "weak", label: "Weak match" };
}

export function relativeTime(iso: string | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const mins = Math.floor((Date.now() - t) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

