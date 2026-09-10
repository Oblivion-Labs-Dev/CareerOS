import { useCallback, useEffect, useRef, useState } from "react";
import { getAutopilotJobsPage } from "@/lib/application-assistant-api";
import type { AutopilotJobRow } from "./job-types";
import type { SortMode, StatusFilter } from "./job-presentation";

const statuses: Record<StatusFilter, string | undefined> = {
  all: undefined, queued: "QUEUED,APPLYING", submitted: "SUBMITTED", review: "NEEDS_REVIEW,STAGED",
  manual: "MANUAL_REVIEW", failed: "FAILED", skipped: "SKIPPED", ineligible: "INELIGIBLE",
};

export function useApplicationPages(filter: StatusFilter, sort: SortMode, query: string) {
  const [jobs, setJobs] = useState<AutopilotJobRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  const [total, setTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [search, setSearch] = useState(query);
  const generation = useRef(0);
  const offset = useRef(0);
  const busy = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => { const timer = setTimeout(() => setSearch(query), 250); return () => clearTimeout(timer); }, [query]);
  const load = useCallback(async (reset = false) => {
    if (busy.current && !reset) return;
    const version = reset ? ++generation.current : generation.current;
    if (reset) { offset.current = 0; setJobs([]); setHasMore(false); }
    busy.current = true; setLoading(true); setError("");
    try {
      const result = await getAutopilotJobsPage({ status: statuses[filter], search,
        sortBy: sort === "match" ? "matchScore" : sort === "recent" ? "submittedAt" : sort,
        sortDir: sort === "company" ? "asc" : "desc", limit: 20, offset: offset.current });
      if (version !== generation.current) return;
      if (!result.success) throw new Error("Could not load applications");
      setJobs(previous => [...new Map([...previous, ...result.jobs].map(job => [job.id, job])).values()]);
      offset.current += result.jobs.length;
      setTotal(result.total); setHasMore(result.hasMore && result.jobs.length > 0);
      const c = result.statusCounts || {};
      setCounts({ all: Object.values(c).reduce((sum, n) => sum + n, 0), submitted: c.SUBMITTED || 0,
        queued: (c.QUEUED || 0) + (c.APPLYING || 0), review: (c.NEEDS_REVIEW || 0) + (c.STAGED || 0),
        manual: c.MANUAL_REVIEW || 0,
        failed: c.FAILED || 0, skipped: c.SKIPPED || 0, ineligible: c.INELIGIBLE || 0 });
    } catch (e) { if (version === generation.current) setError(e instanceof Error ? e.message : "Could not load applications"); }
    finally { if (version === generation.current) { busy.current = false; setLoading(false); } }
  }, [filter, sort, search]);
  const invalidate = useCallback(() => { generation.current++; busy.current = false; }, []);
  useEffect(() => { void load(true); return invalidate; }, [load, revision, invalidate]);
  useEffect(() => {
    if (!hasMore || loading || error || !sentinel.current) return;
    const observer = new IntersectionObserver(entries => { if (entries[0]?.isIntersecting) void load(); }, { rootMargin: "100px" });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasMore, loading, error, load]);
  return { jobs, counts, loading, hasMore, error, total, sentinel, loadMore: () => void load(), refresh: () => setRevision(n => n + 1) };
}
