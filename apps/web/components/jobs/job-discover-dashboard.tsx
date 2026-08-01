"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CareerWorkspaceStrip } from "@/components/career-workspace-strip";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getClientApiBaseUrl } from "@/lib/api";
import { getScraperSyncStatus, importScraperJob, qwenPrepareJob } from "@/lib/application-assistant-api";
import { usePrepQueueStatus } from "@/hooks/use-prep-queue-status";
import { fetchCachedJson, invalidateCachedByPrefix } from "@/lib/client-fetch-cache";
import { isDiscoverCacheFresh, readDiscoverCache, writeDiscoverCache } from "@/lib/job-discover-cache";
import { JobMetaBadges } from "@/components/jobs/job-meta-badges";
import { DiscoverTriageBar, ShortlistToggle } from "@/components/jobs/discover-triage-bar";
import { JobMatchGapPanel, type JobGapAnalysis, type JobGapPanelJob } from "@/components/jobs/job-match-gap-panel";
import {
  matchesTriageFilters,
  triageSignals,
  type AtsSource,
  type Seniority,
} from "@/lib/inbox-triage";

type DiscoverJob = {
  id: string;
  companyName: string;
  title: string;
  location: string;
  url: string;
  description?: string;
  relevancyScore: number;
  color: string;
  keywordsMatched: string[];
  gapAnalysis?: JobGapAnalysis;
  gapAnalysisMethod?: string;
  updatedAt?: string;
  salaryRange?: string;
  employmentType?: string;
  h1bStatus?: "likely" | "unlikely" | "unknown";
  h1bLabel?: string;
  h1bReason?: string;
  h1bSignals?: string[];
  freshness?: { hours_ago: number; label: string; badge_color: string };
};

type DiscoverResponse = {
  success: boolean;
  jobs: DiscoverJob[];
  total: number;
  indexedTotal?: number;
  assistantTotal?: number;
  page: number;
  perPage?: number;
  totalPages: number;
  scrapedAt?: string;
  indexedCompanies?: number;
  status?: { running: boolean; progress: string; lastResult: string };
};

type DiscoverGlobalStats = {
  totalJobs: number;
  indexedCompanies: number;
  strongMatch: number;
  moderateMatch: number;
  fresh48h: number;
  scrapedAt?: string;
};

type LocationOption = {
  value: string;
  label: string;
  count: number;
};

type StatusResponse = {
  success: boolean;
  running: boolean;
  progress: string;
  lastResult: string;
  indexedJobs?: number;
  strongMatches?: number;
  moderateMatches?: number;
  freshMatches?: number;
  indexedCompanies?: number;
  qwenRescore?: {
    running: boolean;
    progress: string;
    lastResult: string;
    scored: number;
    total: number;
  };
  postRescore?: {
    running: boolean;
    phase: string;
    progress: string;
    lastResult: string;
    processed: number;
    total: number;
    qwenRescore?: StatusResponse["qwenRescore"];
  };
  tier1Rescore?: {
    running: boolean;
    progress: string;
    lastResult: string;
    processed: number;
    total: number;
  };
};

type LiveCounts = {
  indexed: number;
  strong: number;
  moderate: number;
  fresh: number;
  companies: number;
};

function liveCountsFromStatus(status: StatusResponse): LiveCounts | null {
  if (status.indexedJobs == null) return null;
  return {
    indexed: status.indexedJobs,
    strong: status.strongMatches ?? 0,
    moderate: status.moderateMatches ?? 0,
    fresh: status.freshMatches ?? 0,
    companies: status.indexedCompanies ?? 0,
  };
}

type FreshnessFilter = "all" | "12" | "24" | "48" | "72" | "168" | "336" | "720";
type SponsorshipFilter = "all" | "likely" | "unlikely" | "friendly";
type ScrapeMode = "ats" | "bigtech" | "apify" | "all";
type SortFilter = "relevancy" | "date" | "company";

const POSTED_AGO_OPTIONS: { value: FreshnessFilter; label: string }[] = [
  { value: "all", label: "Any time" },
  { value: "12", label: "Last 12 hours" },
  { value: "24", label: "Last 24 hours" },
  { value: "48", label: "Last 2 days" },
  { value: "72", label: "Last 3 days" },
  { value: "168", label: "Last 7 days" },
  { value: "336", label: "Last 14 days" },
  { value: "720", label: "Last 30 days" },
];

const LOCATION_QUICK_PICKS = ["Remote", "United States", "Seattle", "San Francisco", "New York", "Austin"];

function postedAgoLabel(value: FreshnessFilter) {
  return POSTED_AGO_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

function formatRefreshed(value?: string) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatScrapeProgress(raw: string, indexed?: number) {
  const boards = raw.replace("ATS companies", "ATS boards").replace("companies", "boards");
  if (indexed != null && indexed > 0) {
    return `${boards} · ${indexed.toLocaleString()} roles saved`;
  }
  return boards;
}

function scoreClass(color: string) {
  if (color === "green") return "discover-score discover-score--green";
  if (color === "yellow") return "discover-score discover-score--yellow";
  if (color === "orange") return "discover-score discover-score--orange";
  return "discover-score";
}

function formatLocationOption(label: string, count: number) {
  const short = label.length > 52 ? `${label.slice(0, 49)}…` : label;
  return `${short} (${count.toLocaleString()})`;
}

export function JobDiscoverDashboard() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { prefs, updatePrefs, snapshot, refresh: refreshWorkspace } = useCareerWorkspace();
  const [q, setQ] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [locationInput, setLocationInput] = useState("");
  const [role, setRole] = useState("");
  const [freshness, setFreshness] = useState<FreshnessFilter>("all");
  const [sponsorship, setSponsorship] = useState<SponsorshipFilter>("all");
  const [sort, setSort] = useState<SortFilter>("relevancy");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<DiscoverResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState("");
  const [liveCounts, setLiveCounts] = useState<LiveCounts | null>(null);
  const [globalStats, setGlobalStats] = useState<DiscoverGlobalStats | null>(null);
  const [locationOptions, setLocationOptions] = useState<LocationOption[]>([]);
  const [syncedAssistantTotal, setSyncedAssistantTotal] = useState(0);
  const [scrapeStuck, setScrapeStuck] = useState(false);
  const lastScrapeProgress = useRef({ message: "", at: Date.now() });
  const [rescoring, setRescoring] = useState(false);
  const [rankingFit, setRankingFit] = useState(false);
  const [fitByJobId, setFitByJobId] = useState<
    Record<string, { verdict: string; overallScore: number; legitimacy?: string }>
  >({});
  const [atsFilter, setAtsFilter] = useState<AtsSource | "all">("all");
  const [seniorityFilter, setSeniorityFilter] = useState<Seniority | "all">("all");
  const [maxAgeDays, setMaxAgeDays] = useState<number | "all">("all");
  const [shortlist, setShortlist] = useState<Set<string>>(() => new Set());
  const [scoringShortlist, setScoringShortlist] = useState(false);
  const [queuedStarts, setQueuedStarts] = useState<Record<string, string>>({});
  const { status: prepQueue, refresh: refreshPrepQueue } = usePrepQueueStatus();

  useEffect(() => {
    if (!prepQueue) return;
    const active = new Set(prepQueue.queuedApplicationIds);
    setQueuedStarts((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const [scraperJobId, appId] of Object.entries(prev)) {
        if (!active.has(appId)) {
          delete next[scraperJobId];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [prepQueue]);
  const [addingToAssistant, setAddingToAssistant] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState("");
  const [error, setError] = useState("");
  const [gapPanelJob, setGapPanelJob] = useState<JobGapPanelJob | null>(null);
  const [gapAnalysis, setGapAnalysis] = useState<JobGapAnalysis | null>(null);
  const [gapLoading, setGapLoading] = useState(false);
  const [gapError, setGapError] = useState("");
  const [tier1Rescoring, setTier1Rescoring] = useState(false);
  const [qwenRescoring, setQwenRescoring] = useState(false);
  const postRescoringRef = useRef(false);
  const skipInitialFetch = useRef(false);
  const initializedFromWorkspace = useRef(false);
  const scrapingRef = useRef(false);
  const rescoringRef = useRef(false);

  useEffect(() => {
    scrapingRef.current = scraping;
  }, [scraping]);

  useEffect(() => {
    rescoringRef.current = rescoring;
  }, [rescoring]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok || cancelled) return;
        const status = (await res.json()) as StatusResponse;
        if (status.running) {
          setScraping(true);
          setScrapeMsg(status.progress || status.lastResult || "Running…");
          const next = liveCountsFromStatus(status);
          if (next) setLiveCounts(next);
        } else if (status.lastResult && status.progress === "Complete") {
          setScrapeMsg(status.lastResult);
          const next = liveCountsFromStatus(status);
          if (next) setLiveCounts(next);
        }
        if (status.tier1Rescore?.running) {
          setTier1Rescoring(true);
        }
        if (status.postRescore?.running) {
          postRescoringRef.current = true;
          setQwenRescoring(true);
        } else if (status.qwenRescore?.running) {
          setQwenRescoring(true);
        }
      } catch {
        /* status unavailable on mount */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (initializedFromWorkspace.current) return;
    initializedFromWorkspace.current = true;
    const nextQ = searchParams.get("q") || prefs.searchQuery || "";
    const nextLocation = searchParams.get("location") || prefs.location || "";
    const nextRole = searchParams.get("role") || prefs.roleFilter || "";
    const nextFreshness = searchParams.get("freshness") || prefs.freshness || "all";
    if (nextQ) setQ(nextQ);
    if (nextLocation) {
      setLocation(nextLocation);
      setLocationInput(nextLocation);
    }
    if (nextRole) setRole(nextRole);
    if (nextFreshness === "12" || nextFreshness === "24" || nextFreshness === "48" || nextFreshness === "72" || nextFreshness === "168" || nextFreshness === "336" || nextFreshness === "720" || nextFreshness === "all") {
      setFreshness(nextFreshness as FreshnessFilter);
    }
  }, [searchParams, prefs.searchQuery, prefs.location, prefs.roleFilter, prefs.freshness]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const trimmed = locationInput.trim();
      if (trimmed === location) return;
      setLocation(trimmed);
      setPage(1);
      updatePrefs({ location: trimmed });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [locationInput, location, updatePrefs]);

  const syncFilterUrl = useCallback(
    (overrides?: Partial<{ q: string; company: string; location: string; role: string; freshness: FreshnessFilter }>) => {
      const params = new URLSearchParams();
      const values = {
        q: overrides?.q ?? q,
        location: overrides?.location ?? location,
        role: overrides?.role ?? role,
        freshness: overrides?.freshness ?? freshness,
      };
      if (values.q.trim()) params.set("q", values.q.trim());
      if (values.location.trim()) params.set("location", values.location.trim());
      if (values.role.trim()) params.set("role", values.role.trim());
      if (values.freshness !== "all") params.set("freshness", values.freshness);
      const qs = params.toString();
      router.replace(qs ? `/jobs/discover?${qs}` : "/jobs/discover", { scroll: false });
    },
    [q, location, role, freshness, router],
  );

  useEffect(() => {
    syncFilterUrl();
  }, [location, q, role, freshness, syncFilterUrl]);

  const loadGlobalStats = useCallback(async () => {
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/stats`, { cache: "no-store" });
      if (!res.ok) return;
      const payload = (await res.json()) as DiscoverGlobalStats & { success?: boolean };
      setGlobalStats({
        totalJobs: payload.totalJobs ?? 0,
        indexedCompanies: payload.indexedCompanies ?? 0,
        strongMatch: payload.strongMatch ?? 0,
        moderateMatch: payload.moderateMatch ?? 0,
        fresh48h: payload.fresh48h ?? 0,
        scrapedAt: payload.scrapedAt,
      });
    } catch {
      /* stats optional */
    }
  }, []);

  const loadLocationOptions = useCallback(async () => {
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/locations`, { cache: "no-store" });
      if (!res.ok) return;
      const payload = (await res.json()) as { success?: boolean; locations?: LocationOption[] };
      setLocationOptions(payload.locations ?? []);
    } catch {
      /* locations optional */
    }
  }, []);

  const loadAssistantSyncStatus = useCallback(async () => {
    try {
      const res = await getScraperSyncStatus();
      setSyncedAssistantTotal(res.syncedTotal ?? 0);
    } catch {
      /* assistant count optional */
    }
  }, []);

  useEffect(() => {
    void loadGlobalStats();
    void loadLocationOptions();
    void loadAssistantSyncStatus();
  }, [loadGlobalStats, loadLocationOptions, loadAssistantSyncStatus]);

  useEffect(() => {
    const cached = readDiscoverCache();
    if (!cached?.jobs.length) return;
    setData({
      success: true,
      jobs: cached.jobs as DiscoverJob[],
      total: cached.total,
      page: 1,
      totalPages: Math.max(1, Math.ceil(cached.total / 30)),
      scrapedAt: cached.scrapedAt,
      indexedCompanies: cached.indexedCompanies,
    });
    setLoading(false);
    if (isDiscoverCacheFresh()) {
      skipInitialFetch.current = true;
    }
  }, []);

  const loadJobs = useCallback(async () => {
    setError("");
    const params = new URLSearchParams({
      q,
      company,
      location,
      role,
      freshness,
      sponsorship,
      sort,
      page: String(page),
    });
    const url = `${getClientApiBaseUrl()}/jobs/discover?${params.toString()}`;

    try {
      const payload = await fetchCachedJson<DiscoverResponse>(url, {
        staleMs: scrapingRef.current ? 0 : undefined,
        timeoutMs: scrapingRef.current || rescoringRef.current ? 60_000 : undefined,
      });
      setData(payload);
      if (payload.status?.running) {
        setScraping(true);
        setScrapeMsg(payload.status.progress || payload.status.lastResult || "Running…");
      }
      if (payload.jobs.length || payload.total) {
        writeDiscoverCache({
          jobs: payload.jobs,
          total: payload.total,
          scrapedAt: payload.scrapedAt,
          indexedCompanies: payload.indexedCompanies,
        });
      }
    } catch {
      const cached = readDiscoverCache();
      if (cached?.jobs.length) {
        setData({
          success: true,
          jobs: cached.jobs as DiscoverJob[],
          total: cached.total,
          page: 1,
          totalPages: Math.max(1, Math.ceil(cached.total / 30)),
          scrapedAt: cached.scrapedAt,
          indexedCompanies: cached.indexedCompanies,
          status: { running: false, progress: "", lastResult: "Showing locally cached results" },
        });
        setError("API unavailable — showing last saved results from this browser.");
      } else {
        setError("Backend offline or job discover unavailable. Start the API and refresh.");
        setData(null);
      }
    } finally {
      setLoading(false);
    }
  }, [q, company, location, role, freshness, sponsorship, sort, page]);

  useEffect(() => {
    if (skipInitialFetch.current) {
      skipInitialFetch.current = false;
      return;
    }
    void loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    if (!scraping) return;

    const pollStatus = async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok) return;
        const status = (await res.json()) as StatusResponse;
        const progress = status.progress || status.lastResult || "Running…";
        const next = liveCountsFromStatus(status);
        if (next) setLiveCounts(next);
        const formatted = formatScrapeProgress(progress, next?.indexed);
        if (formatted !== lastScrapeProgress.current.message) {
          lastScrapeProgress.current = { message: formatted, at: Date.now() };
          setScrapeStuck(false);
        } else if (Date.now() - lastScrapeProgress.current.at > 3 * 60 * 1000) {
          setScrapeStuck(true);
        }
        setScrapeMsg(formatted);
        if (!status.running) {
          setScraping(false);
          setScrapeStuck(false);
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          void loadJobs();
          void loadGlobalStats();
          void loadLocationOptions();
          void loadAssistantSyncStatus();
          void refreshWorkspace();
          return;
        }
        invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
        void loadJobs();
      } catch {
        /* ignore polling errors */
      }
    };

    void pollStatus();
    const id = window.setInterval(() => void pollStatus(), 1500);
    return () => window.clearInterval(id);
  }, [scraping, loadJobs, loadGlobalStats, loadLocationOptions, loadAssistantSyncStatus, refreshWorkspace]);

  useEffect(() => {
    if (!tier1Rescoring) return;

    const pollTier1 = async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok) return;
        const status = (await res.json()) as StatusResponse;
        const tier1 = status.tier1Rescore;
        if (!tier1?.running) {
          setTier1Rescoring(false);
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          await loadJobs();
          if (tier1?.lastResult) {
            setActionMsg(tier1.lastResult);
          }
        } else if (tier1.progress) {
          setActionMsg(`Updating match scores: ${tier1.progress}`);
        }
      } catch {
        /* ignore */
      }
    };

    void pollTier1();
    const id = window.setInterval(() => void pollTier1(), 2500);
    return () => window.clearInterval(id);
  }, [tier1Rescoring, loadJobs]);

  useEffect(() => {
    if (!qwenRescoring) return;

    const pollPostRescore = async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok) return;
        const status = (await res.json()) as StatusResponse;
        const post = status.postRescore;
        const qwen = post?.qwenRescore ?? status.qwenRescore;
        const running = Boolean(post?.running || qwen?.running);
        if (!running) {
          postRescoringRef.current = false;
          setQwenRescoring(false);
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          await loadJobs();
          const note = post?.lastResult || qwen?.lastResult;
          if (note) {
            setActionMsg((prev) => (prev ? `${prev} ${note}` : note));
          }
          return;
        }
        const progress =
          post?.phase === "qwen"
            ? qwen?.progress || post.progress
            : post?.progress;
        if (progress) {
          setActionMsg((prev) => {
            const base = prev.replace(/\sAnalysis:.*$/, "");
            return base ? `${base} Analysis: ${progress}` : `Analysis: ${progress}`;
          });
        }
        if (post?.phase === "gap" && post.processed > 0) {
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          void loadJobs();
        }
      } catch {
        /* ignore polling errors */
      }
    };

    void pollPostRescore();
    const id = window.setInterval(() => void pollPostRescore(), 2000);
    return () => window.clearInterval(id);
  }, [qwenRescoring, loadJobs]);

  const stats = useMemo(() => {
    if (scraping && liveCounts) {
      return {
        strong: liveCounts.strong,
        moderate: liveCounts.moderate,
        fresh: liveCounts.fresh,
      };
    }
    if (globalStats) {
      return {
        strong: globalStats.strongMatch,
        moderate: globalStats.moderateMatch,
        fresh: globalStats.fresh48h,
      };
    }
    const jobs = data?.jobs ?? [];
    return {
      strong: jobs.filter((job) => (job.relevancyScore ?? 0) >= 75).length,
      moderate: jobs.filter((job) => (job.relevancyScore ?? 0) >= 50 && (job.relevancyScore ?? 0) < 75).length,
      fresh: jobs.filter((job) => (job.freshness?.hours_ago ?? 999) <= 48).length,
    };
  }, [scraping, liveCounts, globalStats, data?.jobs]);

  const globalIndexed = globalStats?.totalJobs ?? data?.indexedTotal ?? liveCounts?.indexed ?? 0;
  const filteredTotal = data?.total ?? 0;
  const assistantTotal = Math.max(data?.assistantTotal ?? 0, syncedAssistantTotal);
  const perPage = data?.perPage ?? 30;
  const filtersActive = Boolean(q || company || location || role || freshness !== "all" || sponsorship !== "all");
  const triageFiltersActive = atsFilter !== "all" || seniorityFilter !== "all" || maxAgeDays !== "all";
  const anyFiltersActive = filtersActive || triageFiltersActive || sort !== "relevancy";
  const filterHidingResults = !scraping && filteredTotal === 0 && filtersActive;
  const filterVeryNarrow =
    !scraping && !loading && filtersActive && globalIndexed > 100 && filteredTotal > 0 && filteredTotal <= 30;
  const allInAssistant = !loading && !scraping && filteredTotal === 0 && assistantTotal > 0 && !filtersActive;
  const headerIndexed = scraping && liveCounts ? liveCounts.indexed : globalIndexed;
  const headerCompanies = scraping && liveCounts ? liveCounts.companies : globalStats?.indexedCompanies ?? data?.indexedCompanies ?? 0;

  function removeJobFromList(jobId: string) {
    setData((prev) => {
      if (!prev) return prev;
      const perPage = prev.perPage ?? 30;
      const nextTotal = Math.max(0, prev.total - 1);
      return {
        ...prev,
        jobs: prev.jobs.filter((job) => job.id !== jobId),
        total: nextTotal,
        totalPages: Math.max(1, Math.ceil(nextTotal / perPage) || 1),
        assistantTotal: (prev.assistantTotal ?? syncedAssistantTotal) + 1,
      };
    });
    setSyncedAssistantTotal((prev) => prev + 1);
  }

  async function handleCancelScrape() {
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/scrape/cancel`, { method: "POST" });
      if (!res.ok) throw new Error("Could not cancel scrape");
      setScraping(false);
      setScrapeStuck(false);
      setScrapeMsg("Scrape cancelled — partial results kept.");
      invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
      await loadJobs();
      await loadGlobalStats();
      await loadLocationOptions();
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel scrape.");
    }
  }

  async function handleScrape(hours: number, mode: ScrapeMode = "ats") {
    const cappedHours = Math.min(Math.max(hours, 1), 720);
    setScraping(true);
    setScrapeStuck(false);
    setScrapeMsg("Starting…");
    lastScrapeProgress.current = { message: "Starting…", at: Date.now() };
    setError("");
    invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/scrape`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hours: cappedHours, roles: "", mode }),
      });
      const body = (await res.json().catch(() => ({}))) as { success?: boolean; error?: string; detail?: string };
      if (!res.ok || body.success === false) {
        const detail =
          body.error ||
          (typeof body.detail === "string" ? body.detail : "") ||
          (res.status === 409 ? "A scrape is already running — click Cancel scrape or wait." : "Scrape failed to start");
        throw new Error(detail);
      }
      setScrapeMsg("Scrape started — fetching roles…");
    } catch (err) {
      setScraping(false);
      setScrapeMsg("");
      const message = err instanceof Error ? err.message : "Scrape failed to start";
      setError(message.includes("API") ? message : `Could not start scrape. ${message}`);
    }
  }

  async function handleAddToAssistant(job: DiscoverJob) {
    setActionMsg("");
    setError("");

    if (prepQueue && prepQueue.available <= 0) {
      setActionMsg(`Prep queue full (${prepQueue.queued}/${prepQueue.maxQueue}). Wait for running jobs to finish.`);
      return;
    }

    if (addingToAssistant === job.id || queuedStarts[job.id]) {
      if (queuedStarts[job.id]) {
        setActionMsg(`${job.companyName} is already in the prep queue.`);
      }
      return;
    }

    setAddingToAssistant(job.id);
    try {
      const result = await importScraperJob(job.id);
      const aaJobId = String((result.job as { id?: string })?.id || "");
      let applicationId = result.applicationId;

      if (!result.prepStarted && aaJobId) {
        try {
          const retry = await qwenPrepareJob(aaJobId);
          if (retry.applicationId) applicationId = retry.applicationId;
        } catch {
          /* queue may be full — application still appears in pipeline */
        }
      }

      removeJobFromList(job.id);
      invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
      await loadJobs();
      void loadLocationOptions();
      void loadAssistantSyncStatus();
      if (applicationId) {
        setQueuedStarts((prev) => ({ ...prev, [job.id]: applicationId! }));
      }
      window.dispatchEvent(new CustomEvent("qwen-prep-started"));
      window.dispatchEvent(new CustomEvent("careeros-job-counts-changed"));
      void refreshPrepQueue();

      const destination = applicationId
        ? `/application-assistant?app=${encodeURIComponent(applicationId)}`
        : "/application-assistant#application-queue";
      router.push(destination);

      const queue = result.queue;
      if (result.prepStarted) {
        setActionMsg(
          queue
            ? `Added ${job.companyName} — prep queued (${queue.running} running, ${queue.waiting} waiting).`
            : `Added ${job.companyName} — opening AI Assistant queue.`,
        );
      } else if (result.prepError) {
        setActionMsg(`Added ${job.companyName} to the queue. Prep waiting: ${result.prepError}`);
      } else {
        setActionMsg(`Added ${job.companyName} — opening AI Assistant queue.`);
      }
    } catch (err) {
      setActionMsg(err instanceof Error ? err.message : "Could not add job to AI Assistant.");
    } finally {
      setAddingToAssistant(null);
    }
  }

  const visibleJobs = useMemo(() => {
    const jobs = data?.jobs ?? [];
    return jobs.filter((job) =>
      matchesTriageFilters(
        { id: job.id, title: job.title, url: job.url, updatedAt: job.updatedAt },
        { ats: atsFilter, seniority: seniorityFilter, maxAgeDays },
      ),
    );
  }, [data?.jobs, atsFilter, seniorityFilter, maxAgeDays]);

  const triageHidingRows =
    !loading && (data?.jobs?.length ?? 0) > 0 && visibleJobs.length < (data?.jobs?.length ?? 0);

  function toggleShortlist(jobId: string) {
    setShortlist((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  async function handleScoreShortlist() {
    if (shortlist.size === 0) return;
    setScoringShortlist(true);
    setError("");
    try {
      const jobsToScore = (data?.jobs ?? []).filter((job) => shortlist.has(job.id));
      const next: Record<string, { verdict: string; overallScore: number; legitimacy?: string }> = { ...fitByJobId };
      for (const job of jobsToScore) {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/evaluate-fit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job: {
              id: job.id,
              title: job.title,
              companyName: job.companyName,
              location: job.location,
              url: job.url,
              description: job.description || job.keywordsMatched?.join(" ") || "",
            },
          }),
        });
        if (!res.ok) continue;
        const body = (await res.json()) as {
          evaluation?: { verdict?: string; overallScore?: number; legitimacy?: { verdict?: string } };
        };
        const evaluation = body.evaluation;
        if (evaluation?.verdict != null && evaluation.overallScore != null) {
          next[job.id] = {
            verdict: evaluation.verdict,
            overallScore: evaluation.overallScore,
            legitimacy: evaluation.legitimacy?.verdict,
          };
        }
      }
      setFitByJobId(next);
      setActionMsg(`Scored ${jobsToScore.length} shortlisted role${jobsToScore.length === 1 ? "" : "s"}.`);
    } catch {
      setError("Could not score shortlist.");
    } finally {
      setScoringShortlist(false);
    }
  }

  async function handleRankByFit() {
    setRankingFit(true);
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/rank`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 100 }),
      });
      if (!res.ok) throw new Error("Fit rank failed");
      const body = (await res.json()) as {
        shortlistCount?: number;
        jobs?: Array<{
          id: string;
          rankVerdict?: string;
          rankScore?: number;
          fitEvaluation?: { legitimacy?: { verdict?: string } };
        }>;
      };
      const next: Record<string, { verdict: string; overallScore: number; legitimacy?: string }> = {};
      for (const job of body.jobs ?? []) {
        if (job.id && job.rankVerdict != null && job.rankScore != null) {
          next[job.id] = {
            verdict: job.rankVerdict,
            overallScore: job.rankScore,
            legitimacy: job.fitEvaluation?.legitimacy?.verdict,
          };
        }
      }
      setFitByJobId(next);
      setActionMsg(
        `Ranked ${body.shortlistCount ?? 0} jobs by multi-dimension fit (technical, experience, behavioral, career).`,
      );
    } catch {
      setError("Fit ranking failed. Confirm the API is running.");
    } finally {
      setRankingFit(false);
    }
  }

  async function handleRescore() {
    setRescoring(true);
    setError("");
    setActionMsg("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/rescore?force=true`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Could not refresh match scores");
      const body = (await res.json()) as { started?: boolean; error?: string };
      if (!body.started) {
        setActionMsg(body.error || "Match scores are already up to date.");
        return;
      }
      setTier1Rescoring(true);
      setActionMsg("Updating match scores for all indexed jobs in the background…");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh match scores");
    } finally {
      setRescoring(false);
    }
  }

  async function openGapPanel(job: DiscoverJob) {
    const panelJob: JobGapPanelJob = {
      id: job.id,
      title: job.title,
      companyName: job.companyName,
      location: job.location,
      url: job.url,
      relevancyScore: job.relevancyScore,
    };
    setGapPanelJob(panelJob);
    setGapError("");
    if (job.gapAnalysis) {
      setGapAnalysis(job.gapAnalysis);
      setGapLoading(false);
      return;
    }
    setGapAnalysis(null);
    setGapLoading(true);
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/gap-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jobId: job.id }),
      });
      const body = (await res.json()) as { analysis?: JobGapAnalysis; detail?: string; qwenStarted?: boolean };
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Could not analyze match gap");
      }
      if (!body.analysis) {
        throw new Error("No analysis returned");
      }
      setGapAnalysis(body.analysis);
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          jobs: prev.jobs.map((row) => (row.id === job.id ? { ...row, gapAnalysis: body.analysis } : row)),
        };
      });
      if (body.qwenStarted) {
        postRescoringRef.current = true;
        setQwenRescoring(true);
      }
    } catch (err) {
      setGapError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setGapLoading(false);
    }
  }

  function closeGapPanel() {
    setGapPanelJob(null);
    setGapAnalysis(null);
    setGapError("");
  }

  function clearFilters() {
    setQ("");
    setCompany("");
    setLocation("");
    setLocationInput("");
    setRole("");
    setFreshness("all");
    setSponsorship("all");
    setSort("relevancy");
    setAtsFilter("all");
    setSeniorityFilter("all");
    setMaxAgeDays("all");
    setPage(1);
    updatePrefs({
      searchQuery: "",
      location: "",
      roleFilter: "",
      freshness: "all",
    });
    router.replace("/jobs/discover", { scroll: false });
  }

  function applyLocationFilter(nextLocation: string) {
    setLocationInput(nextLocation);
    setLocation(nextLocation);
    setPage(1);
    updatePrefs({ location: nextLocation });
  }

  function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const nextQ = String(form.get("q") || "");
    const nextCompany = String(form.get("company") || "");
    const nextLocation = String(form.get("location") || "");
    const nextRole = String(form.get("role") || "");
    setQ(nextQ);
    setCompany(nextCompany);
    setLocationInput(nextLocation);
    setLocation(nextLocation);
    setRole(nextRole);
    setPage(1);
    updatePrefs({
      searchQuery: nextQ,
      location: nextLocation,
      roleFilter: nextRole,
      freshness,
    });
  }

  return (
    <div className={`target-jobs-dashboard job-discover-dashboard${scraping ? " job-discover-dashboard--scraping" : ""}`}>
      <CareerWorkspaceStrip active="discover" />
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Multi-ATS scraper</span>
            <h2 className={scraping ? "job-discover-live-count" : undefined}>
              {scraping
                ? `${headerIndexed.toLocaleString()} indexed roles`
                : `${filteredTotal.toLocaleString()} roles to review`}
              {!scraping && filtersActive && filteredTotal !== globalIndexed ? (
                <span className="muted" style={{ fontSize: "0.95rem", fontWeight: 500 }}>
                  {" "}
                  · {filteredTotal.toLocaleString()} match filters
                </span>
              ) : null}
            </h2>
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              Last scraped: {formatRefreshed(globalStats?.scrapedAt ?? data?.scrapedAt)} · {headerCompanies} companies · max 30 days
              {!scraping && assistantTotal > 0 ? ` · ${assistantTotal.toLocaleString()} in AI Assistant` : ""}
              {!scraping && globalIndexed > 0 ? ` · ${globalIndexed.toLocaleString()} indexed total` : ""}
              {scraping && filteredTotal > 0 ? ` · ${filteredTotal.toLocaleString()} match filters` : ""}
              {snapshot?.profile?.targetRole ? ` · scoring for ${snapshot.profile.targetRole}` : ""}
              {scraping ? ` · ${scrapeMsg || "Running…"}` : scrapeMsg ? ` · ${scrapeMsg}` : ""}
            </p>
          </div>
          <div className="target-jobs-actions">
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void handleScrape(24, "ats")} disabled={scraping}>
              {scraping ? "Scraping…" : "Fetch 24h"}
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleScrape(168, "ats")} disabled={scraping}>
              Fetch 7 days
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleScrape(720, "ats")} disabled={scraping}>
              Fetch 30 days
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleScrape(720, "bigtech")} disabled={scraping}>
              Big Tech
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleScrape(720, "all")} disabled={scraping}>
              Fetch all
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleRescore()} disabled={rescoring || tier1Rescoring}>
              {rescoring || tier1Rescoring ? "Updating scores…" : "Refresh all scores"}
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleRankByFit()} disabled={rankingFit}>
              {rankingFit ? "Ranking fit…" : "Rank by fit"}
            </button>
            {scraping ? (
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleCancelScrape()}>
                Cancel scrape
              </button>
            ) : null}
          </div>
        </div>

        <form className="target-jobs-filters job-discover-filters" onSubmit={handleSearch}>
          <label>
            Search
            <input name="q" value={q} onChange={(event) => setQ(event.target.value)} placeholder="Senior software developer" />
          </label>
          <label>
            Company
            <input name="company" value={company} onChange={(event) => setCompany(event.target.value)} placeholder="e.g. stripe" />
          </label>
          <label>
            Location
            <input
              name="location"
              list="job-discover-location-options"
              value={locationInput}
              onChange={(event) => setLocationInput(event.target.value)}
              placeholder="e.g. Remote, Seattle, New York"
              autoComplete="off"
            />
            <datalist id="job-discover-location-options">
              {locationOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {formatLocationOption(opt.label, opt.count)}
                </option>
              ))}
            </datalist>
          </label>
          <label>
            Roles
            <input name="role" value={role} onChange={(event) => setRole(event.target.value)} placeholder="Filter: pm,swe,ux,tpm" title="Filters the table only — scrape always pulls all role types" />
          </label>
          <label>
            Posted ago
            <select
              name="freshness"
              value={freshness}
              onChange={(event) => {
                setFreshness(event.target.value as FreshnessFilter);
                setPage(1);
                updatePrefs({ freshness: event.target.value });
              }}
            >
              {POSTED_AGO_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            H1B / Sponsorship
            <select value={sponsorship} onChange={(event) => { setSponsorship(event.target.value as SponsorshipFilter); setPage(1); }}>
              <option value="all">All jobs</option>
              <option value="likely">H1B friendly</option>
              <option value="friendly">Visa seeker friendly</option>
              <option value="unlikely">Unlikely H1B</option>
            </select>
          </label>
          <label>
            Sort
            <select value={sort} onChange={(event) => { setSort(event.target.value as SortFilter); setPage(1); }}>
              <option value="relevancy">Best match</option>
              <option value="date">Newest</option>
              <option value="company">Company</option>
            </select>
          </label>
          <button type="submit" className="btn btn-sm btn-secondary">Apply filters</button>
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={clearFilters}
            disabled={!anyFiltersActive}
            title="Reset search, location, roles, posted date, sponsorship, sort, and quick filters"
          >
            Clear all filters
          </button>
        </form>

        <div className="job-discover-location-chips" aria-label="Quick location filters">
          <span className="job-discover-location-chips-label">Location:</span>
          <button
            type="button"
            className={`job-discover-location-chip${!location ? " job-discover-location-chip--active" : ""}`}
            onClick={() => applyLocationFilter("")}
          >
            All
          </button>
          {LOCATION_QUICK_PICKS.map((pick) => {
            const active = location.toLowerCase() === pick.toLowerCase();
            return (
              <button
                key={pick}
                type="button"
                className={`job-discover-location-chip${active ? " job-discover-location-chip--active" : ""}`}
                onClick={() => applyLocationFilter(pick)}
              >
                {pick}
              </button>
            );
          })}
        </div>

        <div className="target-jobs-stats">
          <article className="stat-card">
            <p className="stat-label">Strong match</p>
            <p className={`stat-value${scraping ? " job-discover-live-stat" : ""}`}>{stats.strong.toLocaleString()}</p>
          </article>
          <article className="stat-card">
            <p className="stat-label">Moderate</p>
            <p className={`stat-value${scraping ? " job-discover-live-stat" : ""}`}>{stats.moderate.toLocaleString()}</p>
          </article>
          <article className="stat-card">
            <p className="stat-label">Posted &lt;48h</p>
            <p className={`stat-value${scraping ? " job-discover-live-stat" : ""}`}>{stats.fresh.toLocaleString()}</p>
          </article>
          <article className="stat-card">
            <p className="stat-label">In Assistant</p>
            <p className="stat-value">
              <a href="/application-assistant" className="job-discover-assistant-stat-link">
                {assistantTotal.toLocaleString()}
              </a>
            </p>
          </article>
          <article className="stat-card">
            <p className="stat-label">Page</p>
            <p className="stat-value">{data?.page ?? 1}/{data?.totalPages ?? 1}</p>
          </article>
        </div>

        {filterHidingResults ? (
          <p className="email-sender-status email-sender-status--warn">
            No roles match your current filters
            {location ? ` (location: ${location})` : ""}
            {role ? ` (roles: ${role})` : ""}
            {freshness !== "all" ? ` (posted: ${postedAgoLabel(freshness).toLowerCase()})` : ""}
            .{" "}
            <button type="button" className="btn btn-sm btn-secondary" onClick={clearFilters} style={{ marginLeft: "0.35rem" }}>
              Clear filters
            </button>
          </p>
        ) : null}
        {filterVeryNarrow ? (
          <p className="email-sender-status email-sender-status--warn">
            Filters narrowed {globalIndexed.toLocaleString()} indexed roles down to {filteredTotal.toLocaleString()}
            {q ? ` · search: “${q}”` : ""}
            {location ? ` · location: ${location}` : ""}
            {role ? ` · roles: ${role}` : ""}
            {freshness !== "all" ? ` · posted: ${postedAgoLabel(freshness).toLowerCase()}` : ""}
            .{" "}
            <button type="button" className="btn btn-sm btn-secondary" onClick={clearFilters} style={{ marginLeft: "0.35rem" }}>
              Show all roles
            </button>
          </p>
        ) : null}
        {triageHidingRows ? (
          <p className="muted text-sm">
            Quick filters hid {(data?.jobs?.length ?? 0) - visibleJobs.length} of {data?.jobs?.length ?? 0} roles on this page.
            Reset ATS, level, or age chips above to see more.
          </p>
        ) : null}
        {allInAssistant ? (
          <p className="email-sender-status email-sender-status--ok">
            All scraped roles are in AI Assistant ({assistantTotal.toLocaleString()} total).{" "}
            <a href="/application-assistant">Open AI Assistant</a> to review and apply.
          </p>
        ) : null}
        {scraping ? (
          <p className="email-sender-status email-sender-status--ok" role="status" aria-live="polite">
            Scrape in progress: {scrapeMsg || "Starting…"}
            {liveCounts ? ` · ${liveCounts.indexed.toLocaleString()} roles saved so far` : ""}
            {scrapeStuck ? (
              <>
                {" "}
                — appears stuck on the last board.{" "}
                <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleCancelScrape()} style={{ marginLeft: "0.35rem" }}>
                  Cancel and keep partial results
                </button>
              </>
            ) : null}
          </p>
        ) : null}
        {error ? <p className="email-sender-status email-sender-status--warn">{error}</p> : null}
        {!scraping && scrapeMsg ? <p className="muted">{scrapeMsg}</p> : null}
        {actionMsg ? <p className="muted">{actionMsg}</p> : null}
        {prepQueue && (prepQueue.queued > 0 || (prepQueue.openBrowserCount ?? 0) > 0) ? (
          <p className="email-sender-status email-sender-status--ok" role="status">
            Prep queue: {prepQueue.running} running · {prepQueue.waiting} waiting · {prepQueue.available} slots left
            {" "}(max {prepQueue.maxConcurrent} parallel, {prepQueue.maxQueue} total)
            {(prepQueue.openBrowserCount ?? 0) > 0
              ? ` · ${prepQueue.openBrowserCount} browser window${prepQueue.openBrowserCount === 1 ? "" : "s"} open`
              : ""}
            {" · "}
            <a href="/application-assistant">Open AI Assistant</a>
          </p>
        ) : null}
      </section>

      <section className="workflow-panel data-panel">
        <div className="data-panel-header">
          <div>
            <span className="toc-card-kicker">Matches</span>
            <h2>
              {loading
                ? "Loading…"
                : scraping
                  ? `${(data?.total ?? 0).toLocaleString()} to review · ${(liveCounts?.indexed ?? headerIndexed ?? 0).toLocaleString()} indexed`
                  : `${filteredTotal.toLocaleString()} roles to review`}
            </h2>
            {!loading && assistantTotal > 0 ? (
              <p className="muted job-discover-assistant-count">
                <a href="/application-assistant">{assistantTotal.toLocaleString()} in AI Assistant</a>
              </p>
            ) : null}
          </div>
        </div>

        {!loading && !visibleJobs.length ? (
          <p className="muted">
            {filterHidingResults
              ? "Widen or clear filters above to see roles to review."
              : allInAssistant
                ? "Nothing left to review — open AI Assistant to work through your queue."
                : globalIndexed > 0
                  ? "No roles on this page. Try the next page or adjust quick filters."
                  : "No jobs matched. Run a scrape or widen filters. Fill in your profile skills and title for relevancy scoring."}
          </p>
        ) : (
          <>
            {!loading && (data?.jobs?.length ?? 0) > 0 ? (
              <DiscoverTriageBar
                jobs={data?.jobs ?? []}
                atsFilter={atsFilter}
                seniorityFilter={seniorityFilter}
                maxAgeDays={maxAgeDays}
                shortlist={shortlist}
                onAtsFilter={setAtsFilter}
                onSeniorityFilter={setSeniorityFilter}
                onMaxAgeDays={setMaxAgeDays}
                onToggleShortlist={toggleShortlist}
                onClearShortlist={() => setShortlist(new Set())}
                onScoreShortlist={() => void handleScoreShortlist()}
                scoringShortlist={scoringShortlist}
              />
            ) : null}
          <div className="data-list">
            {visibleJobs.map((job, index) => {
              const signals = triageSignals({ id: job.id, title: job.title, url: job.url, updatedAt: job.updatedAt });
              const rowNumber = (page - 1) * perPage + index + 1;
              const inPrepQueue = Boolean(queuedStarts[job.id]);
              const isAdding = addingToAssistant === job.id;
              const queueFull = (prepQueue?.available ?? 1) <= 0;
              const gapPercent = Math.round(
                job.gapAnalysis?.gapPercent ?? Math.max(0, 100 - (job.relevancyScore ?? 0)),
              );
              return (
              <div className="data-row target-job-row job-discover-row" key={job.id}>
                <div className="job-discover-row-main">
                  <div className="job-discover-match-scores">
                    <span className={scoreClass(job.color)} title="Fit score from your profile and uploaded resume">
                      {job.relevancyScore ?? 0}%
                    </span>
                    {gapPercent > 0 ? (
                      <button
                        type="button"
                        className="job-discover-gap-pill"
                        onClick={() => void openGapPanel(job)}
                        title="See what the job requires vs what's missing from your resume"
                      >
                        {gapPercent}% gap
                      </button>
                    ) : null}
                  </div>
                <a className="job-discover-row-link" href={job.url} target="_blank" rel="noreferrer">
                  {fitByJobId[job.id] ? (
                    <span className="phase-pill" title="Multi-dimension fit score">
                      {fitByJobId[job.id].verdict} · {fitByJobId[job.id].overallScore}
                    </span>
                  ) : null}
                  {fitByJobId[job.id]?.legitimacy === "caution" ? (
                    <span className="phase-pill" title="Posting legitimacy check">Review posting</span>
                  ) : null}
                  {fitByJobId[job.id]?.legitimacy === "suspicious" ? (
                    <span className="phase-pill" title="Posting legitimacy check">Caution</span>
                  ) : null}
                  <div>
                    <h3>{job.title}</h3>
                    <span>{job.companyName}</span>
                    <span className="muted text-sm" style={{ display: "block", marginTop: "0.15rem" }}>
                      {signals.seniority ? `${signals.seniority} · ` : ""}
                      {signals.ats !== "other" ? signals.ats : "ATS"}
                    </span>
                    <JobMetaBadges
                      location={job.location || undefined}
                      salaryRange={job.salaryRange}
                      employmentType={job.employmentType}
                      h1bStatus={job.h1bStatus}
                      h1bLabel={job.h1bLabel}
                      h1bReason={job.h1bReason}
                      h1bSignals={job.h1bSignals}
                      freshnessLabel={job.freshness?.label}
                    />
                    {job.keywordsMatched?.length ? (
                      <span className="job-discover-keywords">{job.keywordsMatched.slice(0, 6).join(" · ")}</span>
                    ) : null}
                  </div>
                </a>
                </div>
                <div className="job-discover-row-actions">
                  <span className="job-discover-row-num" title="Position in review queue">#{rowNumber}</span>
                  <ShortlistToggle jobId={job.id} shortlist={shortlist} onToggle={toggleShortlist} />
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    onClick={() => void handleAddToAssistant(job)}
                    disabled={isAdding || inPrepQueue || (queueFull && !inPrepQueue)}
                    title={
                      inPrepQueue
                        ? "Already in prep queue"
                        : queueFull
                          ? "Prep queue is full"
                          : "Add to AI Assistant and start Qwen prep"
                    }
                  >
                    {isAdding ? "Starting…" : inPrepQueue ? "Queued" : "Add to Assistant"}
                  </button>
                  <a className="btn btn-sm btn-primary" href={job.url} target="_blank" rel="noreferrer">
                    Apply
                  </a>
                </div>
              </div>
              );
            })}
          </div>
          </>
        )}

        {(data?.totalPages ?? 0) > 1 ? (
          <div className="job-discover-pagination">
            <button type="button" className="btn btn-sm btn-secondary" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
              Previous
            </button>
            <span className="muted">Page {page} of {data?.totalPages ?? 1}</span>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              disabled={page >= (data?.totalPages ?? 1)}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        ) : null}
      </section>

      <JobMatchGapPanel
        open={Boolean(gapPanelJob)}
        loading={gapLoading}
        error={gapError}
        job={gapPanelJob}
        analysis={gapAnalysis}
        onClose={closeGapPanel}
      />
    </div>
  );
}
