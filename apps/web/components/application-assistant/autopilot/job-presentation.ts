import type { AutopilotJobRow } from "./job-types";

// Flat, literal status names — no "Needs you"/"In progress" grouping layer.
// "submitted" is the one umbrella: it covers everything ever sent (open +
// rejected) so the top-level count reads as "total submitted", and "open"/
// "rejected" are its two drill-down children for when you want just one.
export type StatusFilter =
  | "all"
  | "queued"
  | "review"
  | "manual"
  | "failed"
  | "unverified"
  | "skipped"
  | "ineligible"
  | "submitted"
  | "open"
  | "rejected";

export type SortMode = "priority" | "match" | "recent" | "company";

export const FILTERS: { id: StatusFilter; label: string; match: (j: AutopilotJobRow) => boolean }[] = [
  { id: "all", label: "All applications", match: () => true },
  { id: "queued", label: "Queued", match: (j) => j.status === "QUEUED" || j.status === "APPLYING" },
  { id: "review", label: "In Review", match: (j) => j.status === "NEEDS_REVIEW" || j.status === "STAGED" },
  // Live postings the automation can never finish (a CAPTCHA guards the board,
  // or its form cannot be driven) but the user can submit by hand. Kept apart
  // from Review, where answering a question lets Autopilot carry on, and from
  // Failed, which means there is nothing left to apply to.
  { id: "manual", label: "Manual Review", match: (j) => j.status === "MANUAL_REVIEW" },
  // Dead ends that are never retried: expired or removed postings, broken
  // links, duplicates of an application already sent. Anything retryable lives
  // in Review or Manual Review instead (repo owner, 2026-09-23).
  { id: "failed", label: "Failed", match: (j) => j.status === "FAILED" },
  // The submit button was clicked and no confirmation could be read, so the
  // employer may or may not have the application. Its own bucket because it is
  // the one list where the user must check the posting before doing anything —
  // treating these as Failed is what caused Autopilot to apply a second time.
  { id: "unverified", label: "Unverified", match: (j) => j.status === "SUBMISSION_UNKNOWN" },
  { id: "skipped", label: "Skipped", match: (j) => j.status === "SKIPPED" },
  // Ineligible means only that the candidate is barred from the role (visa
  // sponsorship, US citizenship, an excluded role or company). Kept apart from
  // Skipped and Failed so the lists the user works through stay actionable.
  { id: "ineligible", label: "Ineligible", match: (j) => j.status === "INELIGIBLE" },
  { id: "submitted", label: "Submitted", match: (j) => j.status === "SUBMITTED" || j.status === "REJECTED" },
  { id: "open", label: "Open", match: (j) => j.status === "SUBMITTED" },
  { id: "rejected", label: "Rejected", match: (j) => j.status === "REJECTED" },
];

export const STATUS_QUERIES: Record<StatusFilter, string | undefined> = {
  all: undefined,
  queued: "QUEUED,APPLYING",
  review: "NEEDS_REVIEW,STAGED",
  manual: "MANUAL_REVIEW",
  failed: "FAILED",
  unverified: "SUBMISSION_UNKNOWN",
  skipped: "SKIPPED",
  ineligible: "INELIGIBLE",
  submitted: "SUBMITTED,REJECTED",
  open: "SUBMITTED",
  rejected: "REJECTED",
};

// The direct, always-visible status chips — "open" and "rejected" are reached
// by drilling into "submitted" instead of sitting alongside it, so they are
// left out of this top-level list.
export const STATUS_VIEWS: StatusFilter[] = ["queued", "review", "manual", "failed", "unverified", "skipped", "ineligible", "submitted"];
// Shown only once "submitted" is the active (or ancestor) filter.
export const SUBMITTED_DRILLDOWN: StatusFilter[] = ["open", "rejected"];

export function applicationCounts(statusCounts: Record<string, number>): Record<string, number> {
  return Object.fromEntries(Object.entries(STATUS_QUERIES).map(([key, statuses]) => [key,
    statuses ? statuses.split(",").reduce((sum, status) => sum + (statusCounts[status] || 0), 0)
      : Object.values(statusCounts).reduce((sum, count) => sum + count, 0)]));
}

export const SORTS: { id: SortMode; label: string }[] = [
  { id: "priority", label: "Priority (Senior + Seattle)" },
  { id: "match", label: "Match score" },
  { id: "recent", label: "Most recent" },
  { id: "company", label: "Company A-Z" },
];

/** Mirrors role_location_priority_bonus + queue_priority_score in the API's
 *  job_filter_ranker, so the order shown here is the order Autopilot actually
 *  applies in: Washington Senior SWE, then any related Washington engineering
 *  role, then Senior SWE elsewhere in the US, then the rest.
 *
 *  The backend writes its own computed `queuePriority` onto queued rows; when
 *  that is present it is authoritative and used as-is, so the list can never
 *  drift from the real claim order. The local computation below is the fallback
 *  for rows written before that field existed. */
export function priorityRank(j: AutopilotJobRow): number {
  if (typeof j.queuePriority === "number" && Number.isFinite(j.queuePriority)) {
    return j.queuePriority;
  }
  const t = String(j.title || "").toLowerCase();
  const loc = String(j.location || "").toLowerCase();
  const score = Number(j.matchScore || 0);

  const aboveSenior = ["staff", "principal", "distinguished", "fellow",
    "architect", "director", "head of", "vp ", "vice president"].some((k) => t.includes(k));
  const isSenior = t.includes("senior") || t.includes("sr. ") || t.includes("sr ");
  const isEngineering = ["software", "backend", "back end", "full stack", "fullstack",
    "frontend", "front end", "platform", "infrastructure", "systems", "distributed",
    "engineer", "developer"].some((k) => t.includes(k));
  // "Washington, D.C." is not Washington State — see the same guard in the
  // API's role_location_priority_bonus.
  const isDc = ["district of columbia", "washington, d.c", "washington d.c",
    "washington, dc", "washington dc"].some((k) => loc.includes(k));
  const isWa = !isDc && ["seattle", "bellevue", "redmond", "kirkland", "spokane",
    "tacoma", ", wa", "wa,", "washington"].some((k) => loc.includes(k));
  const isUs = isWa || isDc || ["united states", "usa", "u.s.", "remote"].some((k) => loc.includes(k));

  const seniorSwe = isSenior && isEngineering && !aboveSenior;
  if (seniorSwe && isWa) return score + 120;
  if (isWa && isEngineering) return score + 90;
  if (seniorSwe && isUs) return score + 60;
  if (isUs && isEngineering) return score + 25;
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
  BOT_PROTECTED_BOARD: "Board blocks automation (CAPTCHA)",
  REQUIRES_UNAVAILABLE_INFORMATION: "Needs a detail your profile doesn’t have",
  ROLE_EXCLUDED: "Management/director role — excluded",
  COMPANY_CAP_REACHED: "Company application cap reached",
};

export function statusView(status: string | undefined): { key: string; label: string } {
  switch (status) {
    case "SUBMITTED": return { key: "submitted", label: "Open" };
    case "NEEDS_REVIEW": return { key: "review", label: "In Review" };
    case "STAGED": return { key: "review", label: "In Review" };
    case "MANUAL_REVIEW": return { key: "manual", label: "Manual Review" };
    case "FAILED": return { key: "failed", label: "Failed" };
    case "SUBMISSION_UNKNOWN": return { key: "unverified", label: "Unverified — may have been sent" };
    case "SKIPPED": return { key: "skipped", label: "Skipped" };
    case "APPLYING": return { key: "applying", label: "Applying" };
    case "INELIGIBLE": return { key: "ineligible", label: "Ineligible" };
    case "REJECTED": return { key: "rejected", label: "Rejected" };
    case "QUEUED": return { key: "queued", label: "Queued" };
    case "DISCOVERED": return { key: "discovered", label: "Discovered" };
    case "SCORED": return { key: "scored", label: "Scored" };
    default: return { key: "unknown", label: status || "Unknown status" };
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

/**
 * How long until a company's rate limit frees up.
 *
 * The backend paces applications per employer — 5 a day, 10 a week, 20 a month
 * — and a paced job stays QUEUED carrying `companyCapHoldUntil` rather than
 * moving to a terminal bucket. Without this the card was indistinguishable
 * from any other queued job, so a held posting looked like the queue was
 * simply stuck.
 *
 * Returns null once the hold has expired, so the badge disappears on its own
 * when the window rolls without needing the row to be rewritten.
 */
export function capCountdown(job: {
  companyCapHoldUntil?: string;
  companyCapTier?: string;
}): { label: string; detail: string } | null {
  if (!job.companyCapHoldUntil) return null;
  const until = new Date(job.companyCapHoldUntil).getTime();
  if (Number.isNaN(until)) return null;
  const mins = Math.round((until - Date.now()) / 60000);
  if (mins <= 0) return null;

  const when =
    mins < 60
      ? `${mins}m`
      : mins < 60 * 24
        ? `${Math.round(mins / 60)}h`
        : `${Math.round(mins / (60 * 24))}d`;
  const TIER_LABELS: Record<string, string> = {
    day: "daily limit",
    week: "weekly limit",
    month: "monthly limit",
  };
  const tier = TIER_LABELS[job.companyCapTier || ""] || "application limit";
  return {
    label: `Paced · ${when}`,
    detail: `This employer has reached its ${tier}. Resumes in ${when} — or click Apply to send it now.`,
  };
}

