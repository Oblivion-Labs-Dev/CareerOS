type CacheEntry<T> = {
  data: T;
  fetchedAt: number;
};

const cache = new Map<string, CacheEntry<unknown>>();
const inflight = new Map<string, Promise<unknown>>();

export const DEFAULT_STALE_MS = 30_000;

export function getCached<T>(key: string, maxAgeMs = DEFAULT_STALE_MS): T | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.fetchedAt > maxAgeMs) return null;
  return entry.data as T;
}

export function getCachedStale<T>(key: string): T | null {
  const entry = cache.get(key);
  return entry ? (entry.data as T) : null;
}

export function setCached<T>(key: string, data: T): void {
  cache.set(key, { data, fetchedAt: Date.now() });
}

export function invalidateCached(key: string): void {
  cache.delete(key);
}

export async function fetchCachedJson<T>(
  url: string,
  options?: { staleMs?: number; signal?: AbortSignal; timeoutMs?: number },
): Promise<T> {
  const staleMs = options?.staleMs ?? DEFAULT_STALE_MS;
  const fresh = getCached<T>(url, staleMs);
  if (fresh !== null) return fresh;

  const stale = getCachedStale<T>(url);

  let promise = inflight.get(url);
  if (!promise) {
    promise = (async () => {
      const controller = new AbortController();
      const timeoutMs = options?.timeoutMs ?? 8_000;
      const timer = window.setTimeout(() => controller.abort(), timeoutMs);
      if (options?.signal) {
        options.signal.addEventListener("abort", () => controller.abort(), { once: true });
      }
      try {
        const res = await fetch(url, { cache: "no-store", signal: controller.signal });
        if (!res.ok) throw new Error(`Request failed: ${url}`);
        const data = (await res.json()) as T;
        setCached(url, data);
        return data;
      } finally {
        window.clearTimeout(timer);
      }
    })().finally(() => {
      inflight.delete(url);
    });
    inflight.set(url, promise);
  }

  try {
    return (await promise) as T;
  } catch (err) {
    if (stale !== null) return stale;
    throw err;
  }
}
