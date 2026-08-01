"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApplicationPipelineSection, type TrackerSnapshot } from "@/components/dashboard/application-pipeline-section";
import { CareerWorkspaceStrip } from "@/components/career-workspace-strip";
import { TodayActions } from "@/components/dashboard/today-actions";
import { PageTitleWithStatus } from "@/components/page-title-with-status";
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

type DiscoverPayload = { jobs?: DiscoverJob[] };

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
  const [trackerSnapshot, setTrackerSnapshot] = useState<TrackerSnapshot>(() => {
    return getCachedStale<TrackerSnapshot>(`${getClientApiBaseUrl()}/tracker/summary`) || {};
  });
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

  const applications = trackerSnapshot.applications || [];

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
        fetchCachedJson<TrackerSnapshot>(trackerUrl),
      ]);
      if (jobsPayload.status === "fulfilled") {
        setTopJobs(jobsPayload.value.jobs || []);
      } else {
        throw jobsPayload.reason;
      }
      if (trackerPayload.status === "fulfilled") {
        setTrackerSnapshot(trackerPayload.value);
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

  const followUpCount = useMemo(() => {
    const cutoff = Date.now() - 14 * 86_400_000;
    return applications.filter((app) => {
      const status = (app.status || "").toLowerCase();
      if (!["submitted", "interviewing"].includes(status)) return false;
      const stamp = app.submittedAt || app.updatedAt || app.createdAt || "";
      const time = Date.parse(stamp);
      return !Number.isNaN(time) && time <= cutoff;
    }).length;
  }, [applications]);

  const awaitingDecisionCount = useMemo(
    () => applications.filter((app) => (app.status || "").toLowerCase() === "saved").length,
    [applications],
  );

  const freshMatchCount = useMemo(
    () => topJobs.filter((job) => (job.relevancyScore ?? 0) >= 75).length,
    [topJobs],
  );

  return (
    <div className={styles.minimal}>
      <header className={styles.pageHeader}>
        <div>
          <PageTitleWithStatus className={styles.pageTitle}>Dashboard</PageTitleWithStatus>
          <p className={styles.pageSubtitle}>
            Today&apos;s priorities, top matches, and your application pipeline.
          </p>
        </div>
        <ThemeToggle />
      </header>

      <CareerWorkspaceStrip active="dashboard" />

      <TodayActions
        prefs={prefs}
        freshMatchCount={freshMatchCount}
        followUpCount={followUpCount}
        awaitingDecisionCount={awaitingDecisionCount}
      />

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
                  <span
                    className={styles.matchRing}
                    title="Relevancy uses your profile, uploaded resume, and accomplishments when available"
                  >
                    {job.relevancyScore || 0}%
                  </span>
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

      {loading ? (
        <p className={styles.muted}>Loading application pipeline…</p>
      ) : (
        <ApplicationPipelineSection snapshot={trackerSnapshot} />
      )}
    </div>
  );
}
