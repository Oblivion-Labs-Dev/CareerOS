import type { UserProfile } from "@career-os/core";

const PREFS_KEY = "career-os:workspace:prefs";
const SNAPSHOT_KEY = "career-os:workspace:snapshot";

export const DEFAULT_TARGET_SEARCH = "senior software developer";
export const DEFAULT_ROLE_FILTER = "";

export type CareerWorkspacePrefs = {
  searchQuery: string;
  location: string;
  roleFilter: string;
  freshness: string;
};

export type CareerWorkspaceSnapshot = {
  profile: Partial<UserProfile> | null;
  discoverTotal: number;
  discoverStrongMatches: number;
  discoverScrapedAt?: string;
  applicationsCount: number;
  profileCompleteness: number;
  loadedAt: string;
};

const DEFAULT_PREFS: CareerWorkspacePrefs = {
  searchQuery: "",
  location: "",
  roleFilter: "",
  freshness: "all",
};

function readStorage<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: unknown): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore quota / private mode */
  }
}

export function readWorkspacePrefs(): CareerWorkspacePrefs {
  return { ...DEFAULT_PREFS, ...readStorage<Partial<CareerWorkspacePrefs>>(PREFS_KEY) };
}

export function writeWorkspacePrefs(partial: Partial<CareerWorkspacePrefs>): CareerWorkspacePrefs {
  const next = { ...readWorkspacePrefs(), ...partial };
  writeStorage(PREFS_KEY, next);
  return next;
}

export function readWorkspaceSnapshot(): CareerWorkspaceSnapshot | null {
  return readStorage<CareerWorkspaceSnapshot>(SNAPSHOT_KEY);
}

export function writeWorkspaceSnapshot(snapshot: CareerWorkspaceSnapshot): void {
  writeStorage(SNAPSHOT_KEY, snapshot);
}

export function defaultSearchFromProfile(profile: Partial<UserProfile> | null | undefined): string {
  if (!profile) return DEFAULT_TARGET_SEARCH;
  const target = profile.targetRole?.trim();
  if (target) return target;
  const current = profile.currentTitle?.trim();
  if (current) return current;
  return DEFAULT_TARGET_SEARCH;
}

export function defaultLocationFromProfile(profile: Partial<UserProfile> | null | undefined): string {
  const location = profile?.location?.trim();
  if (!location) return "";
  const lower = location.toLowerCase();
  if (lower.includes("remote")) return "remote";
  if (lower.includes("seattle")) return "seattle";
  if (lower.includes("washington")) return "washington";
  if (lower.includes("california") || lower.includes(", ca")) return "california";
  return location;
}

export function roleFilterFromProfile(profile: Partial<UserProfile> | null | undefined): string {
  const target = (profile?.targetRole || profile?.currentTitle || "").toLowerCase();
  if (!target) return "";
  if (target.includes("product manager") || /\bpm\b/.test(target)) return "pm";
  if (target.includes("program") || target.includes("tpm")) return "tpm";
  if (target.includes("design") || target.includes("ux")) return "ux";
  if (target.includes("engineer") || target.includes("developer") || target.includes("swe")) return "swe";
  return "";
}

export function profileCompleteness(profile: Partial<UserProfile> | null | undefined): number {
  if (!profile) return 0;
  const checks = [
    Boolean(profile.fullName?.trim() || profile.firstName?.trim()),
    Boolean(profile.email?.trim()),
    Boolean(profile.targetRole?.trim() || profile.currentTitle?.trim()),
    Boolean(profile.location?.trim()),
    Boolean((profile as { skills?: string }).skills?.trim()),
    Boolean(profile.workExperience?.length),
  ];
  const score = checks.filter(Boolean).length;
  return Math.round((score / checks.length) * 100);
}

export function buildDiscoverQueryParams(prefs: CareerWorkspacePrefs): URLSearchParams {
  const params = new URLSearchParams();
  if (prefs.searchQuery) params.set("q", prefs.searchQuery);
  if (prefs.location) params.set("location", prefs.location);
  if (prefs.roleFilter) params.set("role", prefs.roleFilter);
  if (prefs.freshness && prefs.freshness !== "all") params.set("freshness", prefs.freshness);
  return params;
}

export function discoverHref(prefs?: Partial<CareerWorkspacePrefs>): string {
  const merged = { ...readWorkspacePrefs(), ...prefs };
  const params = buildDiscoverQueryParams(merged);
  const query = params.toString();
  return query ? `/jobs/discover?${query}` : "/jobs/discover";
}

export function dashboardHref(prefs?: Partial<CareerWorkspacePrefs>): string {
  const merged = { ...readWorkspacePrefs(), ...prefs };
  const params = new URLSearchParams();
  if (merged.searchQuery) params.set("q", merged.searchQuery);
  const query = params.toString();
  return query ? `/dashboard?${query}` : "/dashboard";
}
