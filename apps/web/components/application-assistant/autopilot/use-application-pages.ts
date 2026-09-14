import { useCallback, useEffect, useRef, useState } from "react";
import { getAutopilotJobsPage, getAutopilotStats } from "@/lib/application-assistant-api";
import type { AutopilotJobRow } from "./job-types";
import type { SortMode, StatusFilter } from "./job-presentation";

const statuses: Record<StatusFilter, string | undefined> = {
  all: undefined,
  queued: "QUEUED,APPLYING",
  submitted: "SUBMITTED",
  review: "NEEDS_REVIEW,STAGED",
  manual: "MANUAL_REVIEW",
  failed: "FAILED",
  skipped: "SKIPPED",
  ineligible: "INELIGIBLE",
};

// Global in-memory cache for loaded pages to eliminate tab-switching lag
interface PageCacheEntry {
  jobs: AutopilotJobRow[];
  total: number;
  hasMore: boolean;
  offset: number;
  counts: Record<string, number>;
  companyCounts: Record<string, number>;
  timestamp: number;
}

const pageCache = new Map<string, PageCacheEntry>();

interface AutopilotStatsData {
  statusCounts: Record<string, number>;
  uiCounts: Record<string, number>;
  companyCountsByStatus: Record<string, Record<string, number>>;
  timestamp: number;
}

let globalStats: AutopilotStatsData | null = null;
let statsPromise: Promise<AutopilotStatsData | null> | null = null;

async function fetchStatsCached(): Promise<AutopilotStatsData | null> {
  const now = Date.now();
  if (globalStats && now - globalStats.timestamp < 30_000) {
    return globalStats;
  }
  if (!statsPromise) {
    statsPromise = getAutopilotStats()
      .then((res) => {
        if (res.success) {
          globalStats = {
            statusCounts: res.statusCounts || {},
            uiCounts: res.uiCounts || {},
            companyCountsByStatus: res.companyCountsByStatus || {},
            timestamp: Date.now(),
          };
        }
        return globalStats;
      })
      .catch(() => globalStats)
      .finally(() => {
        statsPromise = null;
      });
  }
  return statsPromise;
}

export function useApplicationPages(
  filter: StatusFilter,
  sort: SortMode,
  query: string,
  company?: string
) {
  const cacheKey = `${filter}:${sort}:${query.trim()}:${company?.trim() || ""}`;
  const initialEntry = pageCache.get(cacheKey);

  const [jobs, setJobs] = useState<AutopilotJobRow[]>(initialEntry ? initialEntry.jobs : []);
  const [counts, setCounts] = useState<Record<string, number>>(
    initialEntry ? initialEntry.counts : globalStats ? globalStats.uiCounts : {}
  );
  const [companyCounts, setCompanyCounts] = useState<Record<string, number>>(() => {
    if (initialEntry && Object.keys(initialEntry.companyCounts).length > 0) {
      return initialEntry.companyCounts;
    }
    if (globalStats && globalStats.companyCountsByStatus[filter]) {
      return globalStats.companyCountsByStatus[filter];
    }
    return {};
  });
  const [loading, setLoading] = useState(!initialEntry);
  const [hasMore, setHasMore] = useState(initialEntry ? initialEntry.hasMore : false);
  const [error, setError] = useState("");
  const [total, setTotal] = useState(initialEntry ? initialEntry.total : 0);
  const [revision, setRevision] = useState(0);
  const [search, setSearch] = useState(query);

  const generation = useRef(0);
  const offset = useRef(initialEntry ? initialEntry.offset : 0);
  const busy = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setSearch(query), 250);
    return () => clearTimeout(timer);
  }, [query]);

  // Load server-side stats for instant tab counts and full company lists
  useEffect(() => {
    void fetchStatsCached().then((stats) => {
      if (!stats) return;
      setCounts((prev) => (Object.keys(prev).length > 0 ? prev : stats.uiCounts));
      setCompanyCounts((prev) => {
        if (Object.keys(prev).length > 0) return prev;
        return stats.companyCountsByStatus[filter] || stats.companyCountsByStatus["all"] || {};
      });
    });
  }, [filter]);

  const load = useCallback(
    async (reset = false) => {
      if (busy.current && !reset) return;
      const version = reset ? ++generation.current : generation.current;

      const currentKey = `${filter}:${sort}:${search.trim()}:${company?.trim() || ""}`;
      const cached = pageCache.get(currentKey);

      if (reset) {
        if (cached && Date.now() - cached.timestamp < 60_000) {
          offset.current = cached.offset;
          setJobs(cached.jobs);
          setTotal(cached.total);
          setHasMore(cached.hasMore);
          setCounts(cached.counts);
          setCompanyCounts(cached.companyCounts);
          setLoading(false);
          // If recent enough, skip re-fetch
          if (Date.now() - cached.timestamp < 15_000) return;
        } else {
          offset.current = 0;
          if (!cached) {
            setJobs([]);
            setHasMore(false);
            setLoading(true);
          }
        }
      }

      busy.current = true;
      setError("");

      try {
        const result = await getAutopilotJobsPage({
          status: statuses[filter],
          search,
          company: company?.trim() || undefined,
          sortBy: sort === "match" ? "matchScore" : sort === "recent" ? "submittedAt" : sort,
          sortDir: sort === "company" ? "asc" : "desc",
          limit: 24,
          offset: offset.current,
        });

        if (version !== generation.current) return;
        if (!result.success) throw new Error("Could not load applications");

        setJobs((prev) => {
          const merged = reset
            ? result.jobs
            : [...new Map([...prev, ...result.jobs].map((j) => [j.id, j])).values()];

          offset.current = reset ? result.jobs.length : offset.current + result.jobs.length;
          setTotal(result.total);
          setHasMore(result.hasMore && result.jobs.length > 0);

          const c = result.statusCounts || {};
          const newCounts = {
            all: Object.values(c).reduce((sum, n) => sum + n, 0),
            submitted: c.SUBMITTED || 0,
            queued: (c.QUEUED || 0) + (c.APPLYING || 0),
            review: (c.NEEDS_REVIEW || 0) + (c.STAGED || 0),
            manual: c.MANUAL_REVIEW || 0,
            failed: c.FAILED || 0,
            skipped: c.SKIPPED || 0,
            ineligible: c.INELIGIBLE || 0,
          };
          setCounts(newCounts);

          const serverCompCounts =
            result.companyCounts && Object.keys(result.companyCounts).length > 0
              ? result.companyCounts
              : globalStats?.companyCountsByStatus[filter] || {};
          setCompanyCounts(serverCompCounts);

          pageCache.set(currentKey, {
            jobs: merged,
            total: result.total,
            hasMore: result.hasMore && result.jobs.length > 0,
            offset: offset.current,
            counts: newCounts,
            companyCounts: serverCompCounts,
            timestamp: Date.now(),
          });

          return merged;
        });
      } catch (e) {
        if (version === generation.current) {
          setError(e instanceof Error ? e.message : "Could not load applications");
        }
      } finally {
        if (version === generation.current) {
          busy.current = false;
          setLoading(false);
        }
      }
    },
    [filter, sort, search, company]
  );

  const invalidate = useCallback(() => {
    generation.current++;
    busy.current = false;
  }, []);

  useEffect(() => {
    void load(true);
    return invalidate;
  }, [filter, sort, search, company, revision, invalidate, load]);

  useEffect(() => {
    if (!hasMore || loading || error || !sentinel.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) void load();
      },
      { rootMargin: "100px" }
    );
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasMore, loading, error, load]);

  const refresh = useCallback(() => {
    pageCache.clear();
    globalStats = null;
    setRevision((n) => n + 1);
  }, []);

  return {
    jobs,
    counts,
    companyCounts,
    loading,
    hasMore,
    error,
    total,
    sentinel,
    loadMore: () => void load(),
    refresh,
  };
}
