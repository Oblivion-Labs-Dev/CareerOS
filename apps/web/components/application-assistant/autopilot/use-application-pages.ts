import { useCallback, useEffect, useRef, useState } from "react";
import { getAutopilotJobsPage, getAutopilotStats } from "@/lib/application-assistant-api";
import type { AutopilotJobRow } from "./job-types";
import { STATUS_QUERIES, applicationCounts, type SortMode, type StatusFilter } from "./job-presentation";

const statuses = STATUS_QUERIES;

/** Rows fetched per page; the next page loads as the list scrolls into view. */
export const PAGE_SIZE = 20;

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
  reasonCounts?: Record<string, number>;
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
    // Only status counts are needed here: the first jobs page of each filter
    // carries its own company/title facets, so skip the ~1 MB facet maps.
    statsPromise = getAutopilotStats({ facets: false })
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
  ats?: string,
  reason?: string
) {
  const cacheKey = `${filter}:${sort}:${query.trim()}:${company?.trim() || ""}:${title?.trim() || ""}:${ats || ""}:${reason || ""}`;
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
  const [reasonCounts, setReasonCounts] = useState<Record<string, number>>(initialEntry?.reasonCounts || {});
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

      const currentKey = `${filter}:${sort}:${search.trim()}:${company?.trim() || ""}:${title?.trim() || ""}:${ats || ""}:${reason || ""}`;
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
          setReasonCounts(cached.reasonCounts || {});
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
          reason: reason || undefined,
          sortBy: sort === "match" ? "matchScore" : sort === "resume" ? "resume" : sort === "recent" ? (filter === "submitted" ? "submittedAt" : "recent") : sort,
          sortDir: sort === "company" ? "asc" : "desc",
          limit: PAGE_SIZE,
          offset: reset ? 0 : offset.current,
          facets: reset,
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

          // Scroll pages are fetched without facets; keep the first page's.
          const prevEntry = reset ? undefined : pageCache.get(currentKey);
          const serverCompCounts = prevEntry
            ? prevEntry.companyCounts
            : result.companyCounts && Object.keys(result.companyCounts).length > 0
              ? result.companyCounts
              : globalStats?.companyCountsByStatus[filter] || {};
          setCompanyCounts(serverCompCounts);

          const serverTitleCounts = prevEntry
            ? prevEntry.titleCounts ?? {}
            : result.titleCounts && Object.keys(result.titleCounts).length > 0
              ? result.titleCounts
              : (globalStats?.titleCountsByStatus && globalStats.titleCountsByStatus[filter]) || {};
          setTitleCounts(serverTitleCounts);
          setAtsCounts(result.atsCounts || {});
          setAtsLabels(result.atsLabels || {});
          setReasonCounts(result.reasonCounts || {});

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
            reasonCounts: result.reasonCounts || {},
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
    [filter, sort, search, company, title, ats, reason]
  );

  const invalidate = useCallback(() => {
    generation.current++;
    busy.current = false;
  }, []);

  useEffect(() => {
    void load(true);
    return invalidate;
  }, [filter, sort, search, company, title, ats, reason, revision, invalidate, load]);

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
    reasonCounts,
    loading,
    hasMore,
    error,
    total,
    sentinel,
    loadMore: () => void load(),
    refresh,
  };
}
