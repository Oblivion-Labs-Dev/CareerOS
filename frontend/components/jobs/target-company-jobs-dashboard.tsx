"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

type TargetJob = {
  id: string;
  company: "Oracle" | "DocuSign";
  title: string;
  location: string;
  url: string;
  tags: string[];
  active: boolean;
  lastSeenAt?: string;
};

type TargetJobsResponse = {
  success: boolean;
  refreshedAt?: string;
  needsWeeklyRefresh?: boolean;
  companies?: Record<string, { total: number; active: number; portalUrl?: string }>;
  jobs: TargetJob[];
  total: number;
};

type CompanyFilter = "all" | "Oracle" | "DocuSign";
type LocationFilter = "all" | "remote" | "washington";

function formatRefreshed(value?: string) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function TargetCompanyJobsDashboard() {
  const [company, setCompany] = useState<CompanyFilter>("all");
  const [location, setLocation] = useState<LocationFilter>("all");
  const [data, setData] = useState<TargetJobsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const [error, setError] = useState("");

  const loadJobs = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({
        company,
        location,
        activeOnly: "true",
      });
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/target-companies?${params.toString()}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error("Could not load target company jobs");
      setData(await res.json());
    } catch {
      setError("Backend offline or target jobs unavailable. Start the API and refresh.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [company, location]);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  const stats = useMemo(() => {
    const jobs = data?.jobs ?? [];
    return {
      oracle: jobs.filter((job) => job.company === "Oracle").length,
      docusign: jobs.filter((job) => job.company === "DocuSign").length,
      remote: jobs.filter((job) => job.tags.includes("remote")).length,
      washington: jobs.filter((job) => job.tags.includes("washington") || job.tags.includes("remote")).length,
    };
  }, [data?.jobs]);

  async function handleRefresh() {
    setRefreshing(true);
    setCopyStatus("");
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/target-companies/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verifyOracle: true }),
      });
      if (!res.ok) throw new Error("Refresh failed");
      await loadJobs();
    } catch {
      setError("Refresh failed. Confirm the API is running.");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleCopyWhatsApp() {
    setCopyStatus("");
    try {
      const params = new URLSearchParams({ company, location });
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/target-companies/whatsapp?${params.toString()}`, {
        cache: "no-store",
      });
      if (!res.ok) throw new Error("Copy failed");
      const payload = (await res.json()) as { text: string };
      await navigator.clipboard.writeText(payload.text);
      setCopyStatus("WhatsApp text copied");
    } catch {
      setCopyStatus("Could not copy WhatsApp text");
    }
  }

  return (
    <div className="target-jobs-dashboard">
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Weekly target pull</span>
            <h2>Oracle & DocuSign roles</h2>
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              Last refreshed: {formatRefreshed(data?.refreshedAt)}
              {data?.needsWeeklyRefresh ? " · due for weekly refresh" : ""}
            </p>
          </div>
          <div className="target-jobs-actions">
            <button type="button" className="btn btn-sm" onClick={() => void handleRefresh()} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh now"}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => void handleCopyWhatsApp()} disabled={!data?.jobs.length}>
              Copy WhatsApp list
            </button>
          </div>
        </div>

        <div className="target-jobs-filters">
          <label>
            Company
            <select value={company} onChange={(event) => setCompany(event.target.value as CompanyFilter)}>
              <option value="all">All</option>
              <option value="Oracle">Oracle</option>
              <option value="DocuSign">DocuSign</option>
            </select>
          </label>
          <label>
            Location
            <select value={location} onChange={(event) => setLocation(event.target.value as LocationFilter)}>
              <option value="all">All US senior SWE</option>
              <option value="remote">Remote</option>
              <option value="washington">Washington + remote</option>
            </select>
          </label>
        </div>

        <div className="target-jobs-stats">
          <article className="stat-card"><p className="stat-label">Oracle</p><p className="stat-value">{stats.oracle}</p></article>
          <article className="stat-card"><p className="stat-label">DocuSign</p><p className="stat-value">{stats.docusign}</p></article>
          <article className="stat-card"><p className="stat-label">Remote</p><p className="stat-value">{stats.remote}</p></article>
          <article className="stat-card"><p className="stat-label">WA + remote</p><p className="stat-value">{stats.washington}</p></article>
        </div>

        {error ? <p className="email-sender-status email-sender-status--warn">{error}</p> : null}
        {copyStatus ? <p className="email-sender-status email-sender-status--ok">{copyStatus}</p> : null}
      </section>

      <section className="workflow-panel data-panel">
        <div className="data-panel-header">
          <div>
            <span className="toc-card-kicker">Matches</span>
            <h2>{loading ? "Loading…" : `${data?.total ?? 0} roles`}</h2>
          </div>
        </div>

        {!loading && !data?.jobs.length ? (
          <p className="muted">No jobs matched. Try Refresh now or widen filters.</p>
        ) : (
          <div className="data-list">
            {(data?.jobs ?? []).map((job) => (
              <a className="data-row target-job-row" href={job.url} key={`${job.company}-${job.id}`} target="_blank" rel="noreferrer">
                <div>
                  <h3>{job.title}</h3>
                  <span>
                    {job.company} · {job.location}
                    {job.tags.length ? ` · ${job.tags.join(", ")}` : ""}
                  </span>
                </div>
                <span className="data-row-action">Open</span>
              </a>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
