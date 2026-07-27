"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CareerWorkspaceStrip } from "@/components/career-workspace-strip";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getClientApiBaseUrl } from "@/lib/api";
import { writeWorkspacePrefs, DEFAULT_TARGET_SEARCH, DEFAULT_ROLE_FILTER } from "@/lib/career-workspace";
import { fetchCachedJson } from "@/lib/client-fetch-cache";
import { isDiscoverCacheFresh, readDiscoverCache, writeDiscoverCache } from "@/lib/job-discover-cache";
import { JobMetaBadges } from "@/components/jobs/job-meta-badges";

type DiscoverJob = {
  id: string;
  companyName: string;
  title: string;
  location: string;
  url: string;
  relevancyScore: number;
  color: string;
  keywordsMatched: string[];
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
  page: number;
  totalPages: number;
  scrapedAt?: string;
  indexedCompanies?: number;
  status?: { running: boolean; progress: string; lastResult: string };
};

type StatusResponse = {
  success: boolean;
  running: boolean;
  progress: string;
  lastResult: string;
  indexedJobs?: number;
};

type FreshnessFilter = "all" | "24" | "48" | "168" | "720";
type SponsorshipFilter = "all" | "likely" | "unlikely" | "friendly";
type ScrapeMode = "ats" | "bigtech" | "apify" | "all";
type SortFilter = "relevancy" | "date" | "company";

function formatRefreshed(value?: string) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function scoreClass(color: string) {
  if (color === "green") return "discover-score discover-score--green";
  if (color === "yellow") return "discover-score discover-score--yellow";
  if (color === "orange") return "discover-score discover-score--orange";
  return "discover-score";
}

export function JobDiscoverDashboard() {
  const searchParams = useSearchParams();
  const { prefs, updatePrefs, snapshot, refresh: refreshWorkspace } = useCareerWorkspace();
  const [q, setQ] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [role, setRole] = useState("");
  const [freshness, setFreshness] = useState<FreshnessFilter>("all");
  const [sponsorship, setSponsorship] = useState<SponsorshipFilter>("all");
  const [sort, setSort] = useState<SortFilter>("relevancy");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<DiscoverResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState("");
  const [rescoring, setRescoring] = useState(false);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [actionMsg, setActionMsg] = useState("");
  const [error, setError] = useState("");
  const skipInitialFetch = useRef(false);
  const initializedFromWorkspace = useRef(false);

  useEffect(() => {
    if (initializedFromWorkspace.current) return;
    initializedFromWorkspace.current = true;
    const nextQ = searchParams.get("q") || prefs.searchQuery || DEFAULT_TARGET_SEARCH;
    const nextLocation = searchParams.get("location") || prefs.location || "";
    const nextRole = searchParams.get("role") || prefs.roleFilter || DEFAULT_ROLE_FILTER;
    const nextFreshness = searchParams.get("freshness") || prefs.freshness || "all";
    if (nextQ) setQ(nextQ);
    if (nextLocation) setLocation(nextLocation);
    if (nextRole) setRole(nextRole);
    if (nextFreshness === "24" || nextFreshness === "48" || nextFreshness === "168" || nextFreshness === "720" || nextFreshness === "all") {
      setFreshness(nextFreshness);
    }
    updatePrefs({
      searchQuery: nextQ,
      location: nextLocation,
      roleFilter: nextRole,
      freshness: nextFreshness,
    });
  }, [prefs, searchParams, updatePrefs]);

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
      const payload = await fetchCachedJson<DiscoverResponse>(url);
      setData(payload);
      setScraping(Boolean(payload.status?.running));
      setScrapeMsg(payload.status?.progress || payload.status?.lastResult || "");
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
    const id = window.setInterval(async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok) return;
        const status = (await res.json()) as StatusResponse;
        const progress = status.progress || status.lastResult || "";
        const indexed = status.indexedJobs;
        setScrapeMsg(
          indexed != null && indexed > 0 ? `${progress} · ${indexed.toLocaleString()} indexed` : progress,
        );
        void loadJobs();
        if (!status.running) {
          setScraping(false);
          void loadJobs();
        }
      } catch {
        /* ignore polling errors */
      }
    }, 3000);
    return () => window.clearInterval(id);
  }, [scraping, loadJobs]);

  const stats = useMemo(() => {
    const jobs = data?.jobs ?? [];
    return {
      strong: jobs.filter((job) => (job.relevancyScore ?? 0) >= 75).length,
      moderate: jobs.filter((job) => (job.relevancyScore ?? 0) >= 50 && (job.relevancyScore ?? 0) < 75).length,
      fresh: jobs.filter((job) => (job.freshness?.hours_ago ?? 999) <= 48).length,
    };
  }, [data?.jobs]);

  async function handleScrape(hours: number, mode: ScrapeMode = "ats") {
    const cappedHours = Math.min(Math.max(hours, 1), 720);
    setScraping(true);
    setScrapeMsg("Starting...");
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/scrape`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hours: cappedHours, roles: role, mode }),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(detail || "Scrape failed to start");
      }
    } catch (err) {
      setScraping(false);
      const message = err instanceof Error ? err.message : "Scrape failed to start";
      setError(message.includes("API") ? message : `Could not start scrape. ${message}`);
    }
  }

  async function handleSaveJob(jobId: string) {
    setActionMsg("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/${encodeURIComponent(jobId)}/save`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Save failed");
      setSavedIds((prev) => new Set(prev).add(jobId));
      setActionMsg("Saved to Applications tracker.");
    } catch {
      setActionMsg("Could not save job to tracker.");
    }
  }

  async function handleOutreach(job: DiscoverJob) {
    setActionMsg("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/${encodeURIComponent(job.id)}/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contactName: "[Name]" }),
      });
      if (!res.ok) throw new Error("Outreach failed");
      const payload = (await res.json()) as { message?: string; recruiter_url?: string };
      if (payload.message) {
        await navigator.clipboard.writeText(payload.message);
        setActionMsg(`Outreach copied for ${job.companyName}.`);
      }
      if (payload.recruiter_url) {
        window.open(payload.recruiter_url, "_blank", "noopener,noreferrer");
      }
    } catch {
      setActionMsg("Could not generate outreach message.");
    }
  }

  async function handleRescore() {
    setRescoring(true);
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/rescore`, { method: "POST" });
      if (!res.ok) throw new Error("Rescore failed");
      await loadJobs();
      await refreshWorkspace();
    } catch {
      setError("Rescore failed. Confirm the API is running.");
    } finally {
      setRescoring(false);
    }
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
    <div className="target-jobs-dashboard job-discover-dashboard">
      <CareerWorkspaceStrip active="discover" />
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Multi-ATS scraper</span>
            <h2>{data?.total?.toLocaleString() ?? "…"} indexed roles</h2>
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              Last scraped: {formatRefreshed(data?.scrapedAt)} · {data?.indexedCompanies ?? 0} companies · max 30 days
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
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleRescore()} disabled={rescoring}>
              {rescoring ? "Rescoring…" : "Rescore"}
            </button>
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
            <input name="location" value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Remote, Seattle…" />
          </label>
          <label>
            Roles
            <input name="role" value={role} onChange={(event) => setRole(event.target.value)} placeholder="pm,swe,ux,tpm" />
          </label>
          <label>
            Freshness
            <select value={freshness} onChange={(event) => { setFreshness(event.target.value as FreshnessFilter); setPage(1); }}>
              <option value="all">All</option>
              <option value="24">24 hours</option>
              <option value="48">48 hours</option>
              <option value="168">7 days</option>
              <option value="720">30 days</option>
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
        </form>

        <div className="target-jobs-stats">
          <article className="stat-card"><p className="stat-label">Strong match</p><p className="stat-value">{stats.strong}</p></article>
          <article className="stat-card"><p className="stat-label">Moderate</p><p className="stat-value">{stats.moderate}</p></article>
          <article className="stat-card"><p className="stat-label">Fresh (&lt;48h)</p><p className="stat-value">{stats.fresh}</p></article>
          <article className="stat-card"><p className="stat-label">Page</p><p className="stat-value">{data?.page ?? 1}/{data?.totalPages ?? 1}</p></article>
        </div>

        {error ? <p className="email-sender-status email-sender-status--warn">{error}</p> : null}
        {actionMsg ? <p className="muted">{actionMsg}</p> : null}
      </section>

      <section className="workflow-panel data-panel">
        <div className="data-panel-header">
          <div>
            <span className="toc-card-kicker">Matches</span>
            <h2>{loading ? "Loading…" : `${data?.total ?? 0} roles on this page set`}</h2>
          </div>
        </div>

        {!loading && !data?.jobs.length ? (
          <p className="muted">No jobs matched. Run a scrape or widen filters. Fill in your profile skills and title for relevancy scoring.</p>
        ) : (
          <div className="data-list">
            {(data?.jobs ?? []).map((job) => (
              <div className="data-row target-job-row job-discover-row" key={job.id}>
                <a className="job-discover-row-main job-discover-row-link" href={job.url} target="_blank" rel="noreferrer">
                  <span className={scoreClass(job.color)}>{job.relevancyScore ?? 0}%</span>
                  <div>
                    <h3>{job.title}</h3>
                    <span>{job.companyName}</span>
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
                <div className="job-discover-row-actions">
                  <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleSaveJob(job.id)} disabled={savedIds.has(job.id)}>
                    {savedIds.has(job.id) ? "Saved" : "Save"}
                  </button>
                  <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleOutreach(job)}>
                    Outreach
                  </button>
                  <a className="btn btn-sm btn-primary" href={job.url} target="_blank" rel="noreferrer">
                    Apply
                  </a>
                </div>
              </div>
            ))}
          </div>
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
    </div>
  );
}
