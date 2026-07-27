"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CareerWorkspaceStrip } from "@/components/career-workspace-strip";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getClientApiBaseUrl } from "@/lib/api";
import { discoverHref } from "@/lib/career-workspace";
import { fetchCachedJson, getCachedStale } from "@/lib/client-fetch-cache";
import { DEFAULT_ROLE_FILTER, DEFAULT_TARGET_SEARCH } from "@/lib/career-workspace";
import styles from "./minimal-dashboard.module.css";

type DiscoverJob = {
  id: string;
  companyName: string;
  title: string;
  location: string;
  url: string;
  relevancyScore: number;
  keywordsMatched?: string[];
  freshness?: { label: string };
};

const CARD_TONES = [
  styles.matchCardTone0,
  styles.matchCardTone1,
  styles.matchCardTone2,
  styles.matchCardTone3,
  styles.matchCardTone4,
];

type TrackerApplication = {
  id?: string;
  roleTitle?: string;
  title?: string;
  companyName?: string;
  company?: string;
  status?: string;
  submittedAt?: string;
  updatedAt?: string;
  createdAt?: string;
  url?: string;
};

type DiscoverPayload = { jobs?: DiscoverJob[] };
type TrackerPayload = { applications?: TrackerApplication[] };

type AppFilter = "submitted" | "all";

function relativeTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const diffMs = Date.now() - date.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `${Math.max(mins, 1)}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function appCompany(app: TrackerApplication) {
  return app.companyName || app.company || "Unknown company";
}

function appRole(app: TrackerApplication) {
  return app.roleTitle || app.title || "Unknown role";
}

function appDate(app: TrackerApplication) {
  return app.submittedAt || app.updatedAt || app.createdAt || "";
}

function statusLabel(status?: string) {
  const normalized = (status || "saved").replace(/_/g, " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function companyInitial(name: string) {
  return (name.trim()[0] || "?").toUpperCase();
}

export function MinimalDashboard() {
  const { prefs } = useCareerWorkspace();
  const [topJobs, setTopJobs] = useState<DiscoverJob[]>(() => {
    const api = getClientApiBaseUrl();
    const params = new URLSearchParams({
      q: DEFAULT_TARGET_SEARCH,
      location: "",
      role: DEFAULT_ROLE_FILTER,
      freshness: "168",
      sort: "relevancy",
      page: "1",
      per_page: "5",
    });
    return getCachedStale<DiscoverPayload>(`${api}/jobs/discover?${params.toString()}`)?.jobs || [];
  });
  const [applications, setApplications] = useState<TrackerApplication[]>(() => {
    const cached = getCachedStale<TrackerPayload>(`${getClientApiBaseUrl()}/tracker/summary`);
    return cached?.applications || [];
  });
  const [appFilter, setAppFilter] = useState<AppFilter>("submitted");
  const [loading, setLoading] = useState(() => {
    const api = getClientApiBaseUrl();
    const params = new URLSearchParams({
      q: DEFAULT_TARGET_SEARCH,
      role: DEFAULT_ROLE_FILTER,
      freshness: "168",
      sort: "relevancy",
      page: "1",
      per_page: "5",
    });
    return !(getCachedStale(`${api}/jobs/discover?${params}`) && getCachedStale(`${api}/tracker/summary`));
  });
  const [error, setError] = useState("");

  const loadData = useCallback(async () => {
    const api = getClientApiBaseUrl();
    const jobsUrl = `${api}/jobs/discover?${new URLSearchParams({
      q: prefs.searchQuery || DEFAULT_TARGET_SEARCH,
      location: prefs.location || "",
      role: prefs.roleFilter || DEFAULT_ROLE_FILTER,
      freshness: prefs.freshness || "168",
      sort: "relevancy",
      page: "1",
      per_page: "5",
    })}`;
    const trackerUrl = `${api}/tracker/summary`;

    if (!getCachedStale(jobsUrl) || !getCachedStale(trackerUrl)) {
      setLoading(true);
    }
    setError("");
    try {
      const [jobsPayload, trackerPayload] = await Promise.allSettled([
        fetchCachedJson<DiscoverPayload>(jobsUrl),
        fetchCachedJson<TrackerPayload>(trackerUrl),
      ]);
      if (jobsPayload.status === "fulfilled") {
        setTopJobs(jobsPayload.value.jobs || []);
      } else {
        throw jobsPayload.reason;
      }
      if (trackerPayload.status === "fulfilled") {
        setApplications(trackerPayload.value.applications || []);
      }
    } catch {
      setError("Could not load dashboard. Start the API at " + getClientApiBaseUrl());
    } finally {
      setLoading(false);
    }
  }, [prefs.searchQuery, prefs.location, prefs.roleFilter, prefs.freshness]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const submittedCount = useMemo(
    () => applications.filter((app) => (app.status || "").toLowerCase() === "submitted").length,
    [applications]
  );

  const visibleApps = useMemo(() => {
    return applications
      .filter((app) => appFilter === "all" || (app.status || "").toLowerCase() === "submitted")
      .sort((a, b) => appDate(b).localeCompare(appDate(a)))
      .slice(0, 10);
  }, [applications, appFilter]);

  return (
    <div className={styles.minimal}>
      <header className={styles.pageHeader}>
        <div>
          <h1 className={styles.pageTitle}>Dashboard</h1>
          <p className={styles.pageSubtitle}>Track applications from ApplyPilot and browse scored roles.</p>
        </div>
        <ThemeToggle />
      </header>

      <CareerWorkspaceStrip active="dashboard" />

      {error ? <p className={styles.errorBanner}>{error}</p> : null}

      <section className={styles.matchesSection}>
        <div className={styles.sectionHeader}>
          <h2>Top job matches</h2>
          <Link href={discoverHref(prefs)} className={styles.linkAction}>
            Open Job Scraper →
          </Link>
        </div>

        {loading ? (
          <p className={styles.muted}>Loading matches…</p>
        ) : topJobs.length ? (
          <div className={styles.matchGrid}>
            {topJobs.slice(0, 5).map((job, index) => (
              <article key={job.id} className={`${styles.matchCard} ${CARD_TONES[index % CARD_TONES.length]}`}>
                <div className={styles.matchMeta}>
                  <span>
                    {job.location || "United States"} · {job.freshness?.label || "Recently posted"}
                  </span>
                  <span className={styles.matchRing}>{job.relevancyScore || 0}%</span>
                </div>
                <h3 className={styles.matchTitle}>{job.title}</h3>
                <div className={styles.tagRow}>
                  {(job.keywordsMatched || []).slice(0, 3).map((tag) => (
                    <span key={tag} className={styles.tag}>
                      {tag.replace(/^\+/, "")}
                    </span>
                  ))}
                </div>
                <div className={styles.matchFooter}>
                  <div className={styles.companyRow}>
                    <span className={styles.companyAvatar}>{companyInitial(job.companyName)}</span>
                    <span className={styles.companyName}>{job.companyName}</span>
                  </div>
                  <div className={styles.cardActions}>
                    <button type="button" className={styles.btnPass}>
                      Pass
                    </button>
                    <a href={job.url} target="_blank" rel="noreferrer" className={styles.btnApply}>
                      Apply
                    </a>
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className={styles.empty}>
            No matches yet.{" "}
            <Link href="/profile">Complete your profile</Link>, then run a scrape on{" "}
            <Link href={discoverHref(prefs)}>Job Scraper</Link>.
          </p>
        )}
      </section>

      <section className={styles.panel}>
        <div className={styles.panelHead}>
          <h2>Applications</h2>
          <div className={styles.filterPills}>
            <button
              type="button"
              className={appFilter === "submitted" ? styles.pillActive : styles.pill}
              onClick={() => setAppFilter("submitted")}
            >
              Submitted ({submittedCount})
            </button>
            <button
              type="button"
              className={appFilter === "all" ? styles.pillActive : styles.pill}
              onClick={() => setAppFilter("all")}
            >
              All ({applications.length})
            </button>
          </div>
        </div>

        {loading ? (
          <p className={styles.muted}>Loading…</p>
        ) : visibleApps.length ? (
          <ul className={styles.appList}>
            {visibleApps.map((app, index) => (
              <li key={app.id || `${appCompany(app)}-${index}`} className={styles.appRow}>
                <div className={styles.appMain}>
                  <strong>{appCompany(app)}</strong>
                  <span>{appRole(app)}</span>
                </div>
                <div className={styles.appMeta}>
                  <span className={styles.statusTag}>{statusLabel(app.status)}</span>
                  <span className={styles.muted}>{relativeTime(appDate(app))}</span>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.empty}>
            No submitted applications yet. Use ApplyPilot on a job site, or save roles from{" "}
            <Link href={discoverHref(prefs)}>Job Scraper</Link>.
          </p>
        )}
      </section>
    </div>
  );
}
