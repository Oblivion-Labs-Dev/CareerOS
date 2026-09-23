import { useCallback, useEffect, useRef, useState } from "react";
import { getAutopilotJobsPage, getAutopilotStats } from "@/lib/application-assistant-api";
import type { AutopilotJobRow } from "./job-types";
import { STATUS_QUERIES, applicationCounts, type SortMode, type StatusFilter } from "./job-presentation";

const statuses = STATUS_QUERIES;

// Global in-memory cache for loaded pages to eliminate tab-switching lag
interface PageCacheEntry {
  jobs: AutopilotJobRow[];
  total: number;
  hasMore: boolean;
  offset: number;
  counts: Record<string, number>;
  companyCounts: Record<string, number>;
  titleCounts?: Record<string, number>;
  atsCounts?: Record<string, number>;
  atsLabels?: Record<string, string>;
  timestamp: number;
}

const pageCache = new Map<string, PageCacheEntry>();

interface AutopilotStatsData {
  statusCounts: Record<string, number>;
  uiCounts: Record<string, number>;
  companyCountsByStatus: Record<string, Record<string, number>>;
  titleCountsByStatus?: Record<string, Record<string, number>>;
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
            uiCounts: applicationCounts(res.statusCounts || {}),
            companyCountsByStatus: res.companyCountsByStatus || {},
            titleCountsByStatus: res.titleCountsByStatus || {},
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
  company?: string,
  title?: string,
  ats?: string
) {
  const cacheKey = `${filter}:${sort}:${query.trim()}:${company?.trim() || ""}:${title?.trim() || ""}:${ats || ""}`;
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
  const [titleCounts, setTitleCounts] = useState<Record<string, number>>(() => {
    if (initialEntry && initialEntry.titleCounts && Object.keys(initialEntry.titleCounts).length > 0) {
      return initialEntry.titleCounts;
    }
    if (globalStats && globalStats.titleCountsByStatus && globalStats.titleCountsByStatus[filter]) {
      return globalStats.titleCountsByStatus[filter];
    }
    return {};
  });
  const [atsCounts, setAtsCounts] = useState<Record<string, number>>(initialEntry?.atsCounts || {});
  const [atsLabels, setAtsLabels] = useState<Record<string, string>>(initialEntry?.atsLabels || {});
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

  // Load server-side stats for instant tab counts and full company and title lists
  useEffect(() => {
    void fetchStatsCached().then((stats) => {
      if (!stats) return;
      setCounts((prev) => (Object.keys(prev).length > 0 ? prev : stats.uiCounts));
      setCompanyCounts((prev) => {
        if (Object.keys(prev).length > 0) return prev;
        return stats.companyCountsByStatus[filter] || stats.companyCountsByStatus["all"] || {};
      });
      setTitleCounts((prev) => {
        if (Object.keys(prev).length > 0) return prev;
        return (stats.titleCountsByStatus && (stats.titleCountsByStatus[filter] || stats.titleCountsByStatus["all"])) || {};
      });
    });
  }, [filter]);

  const load = useCallback(
    async (reset = false) => {
      if (busy.current && !reset) return;
      const version = reset ? ++generation.current : generation.current;

      const currentKey = `${filter}:${sort}:${search.trim()}:${company?.trim() || ""}:${title?.trim() || ""}:${ats || ""}`;
      const cached = pageCache.get(currentKey);

      if (reset) {
        if (cached && Date.now() - cached.timestamp < 60_000) {
          offset.current = cached.offset;
          setJobs(cached.jobs);
          setTotal(cached.total);
          setHasMore(cached.hasMore);
          setCounts(cached.counts);
          setCompanyCounts(cached.companyCounts);
          setTitleCounts(cached.titleCounts || {});
          setAtsCounts(cached.atsCounts || {});
          setAtsLabels(cached.atsLabels || {});
          setLoading(false);
          // If recent enough, skip re-fetch
          if (Date.now() - cached.timestamp < 15_000) { busy.current = false; return; }
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
          title: title?.trim() || undefined,
          ats: ats || undefined,
          sortBy: sort === "match" ? "matchScore" : sort === "recent" ? "submittedAt" : sort,
          sortDir: sort === "company" ? "asc" : "desc",
          limit: 24,
          offset: reset ? 0 : offset.current,
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
          const newCounts = applicationCounts(c);
          setCounts(newCounts);

          const serverCompCounts =
            result.companyCounts && Object.keys(result.companyCounts).length > 0
              ? result.companyCounts
              : globalStats?.companyCountsByStatus[filter] || {};
          setCompanyCounts(serverCompCounts);

          const serverTitleCounts =
            result.titleCounts && Object.keys(result.titleCounts).length > 0
              ? result.titleCounts
              : (globalStats?.titleCountsByStatus && globalStats.titleCountsByStatus[filter]) || {};
          setTitleCounts(serverTitleCounts);
          setAtsCounts(result.atsCounts || {});
          setAtsLabels(result.atsLabels || {});

          pageCache.set(currentKey, {
            jobs: merged,
            total: result.total,
            hasMore: result.hasMore && result.jobs.length > 0,
            offset: offset.current,
            counts: newCounts,
            companyCounts: serverCompCounts,
            titleCounts: serverTitleCounts,
            atsCounts: result.atsCounts || {},
            atsLabels: result.atsLabels || {},
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
    [filter, sort, search, company, title, ats]
  );

  const invalidate = useCallback(() => {
    generation.current++;
    busy.current = false;
  }, []);

  useEffect(() => {
    void load(true);
    return invalidate;
  }, [filter, sort, search, company, title, ats, revision, invalidate, load]);

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
    titleCounts,
    atsCounts,
    atsLabels,
    loading,
    hasMore,
    error,
    total,
    sentinel,
    loadMore: () => void load(),
    refresh,
  };
}
