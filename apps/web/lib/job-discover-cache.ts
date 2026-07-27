const CACHE_KEY = "career-os:job-discover:snapshot";
export const DISCOVER_CACHE_TTL_MS = 60_000;

export type CachedDiscoverSnapshot = {
  jobs: unknown[];
  total: number;
  scrapedAt?: string;
  indexedCompanies?: number;
  savedAt: string;
};

export function readDiscoverCache(): CachedDiscoverSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedDiscoverSnapshot;
    if (!parsed || !Array.isArray(parsed.jobs)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function isDiscoverCacheFresh(maxAgeMs = DISCOVER_CACHE_TTL_MS): boolean {
  const cached = readDiscoverCache();
  if (!cached?.savedAt) return false;
  const savedAt = new Date(cached.savedAt).getTime();
  if (Number.isNaN(savedAt)) return false;
  return Date.now() - savedAt <= maxAgeMs;
}

export function writeDiscoverCache(payload: {
  jobs: unknown[];
  total: number;
  scrapedAt?: string;
  indexedCompanies?: number;
}): void {
  if (typeof window === "undefined") return;
  try {
    const snapshot: CachedDiscoverSnapshot = {
      ...payload,
      savedAt: new Date().toISOString(),
    };
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(snapshot));
  } catch {
    /* ignore quota / private mode errors */
  }
}
