"use client";

import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import { EmptyState } from "@/components/ui/feedback";
import { ProgressProvider } from "@/components/career-progress/progress-provider";
import { ProgressHeader } from "@/components/career-progress/progress-header";
import { QuestBoard } from "@/components/career-progress/quest-board";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApplicationAnalytics } from "@/components/dashboard/application-analytics";
import { SearchIntelligence } from "./search-intelligence";
import { ApplicationInsights } from "@/components/dashboard/application-insights";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getApiOriginForDisplay, getClientApiBaseUrl } from "@/lib/api";
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


type DiscoverPayload = { jobs?: DiscoverJob[] };

function companyInitial(name: string) {
  return (name.trim()[0] || "?").toUpperCase();
}

function scoreTone(score: number) {
  if (score >= 75) return styles.matchRingStrong;
  if (score >= 55) return styles.matchRingModerate;
  return styles.matchRingLow;
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
    return !getCachedStale(`${api}/jobs/discover?${params}`);
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
    if (!getCachedStale(jobsUrl)) {
      setLoading(true);
    }
    setError("");
    try {
      const jobsPayload = await fetchCachedJson<DiscoverPayload>(jobsUrl);
      setTopJobs(jobsPayload.jobs || []);
    } catch {
      setError("Could not load dashboard. Start the API at " + getApiOriginForDisplay());
    } finally {
      setLoading(false);
    }
  }, [prefs.searchQuery, prefs.location, prefs.roleFilter, prefs.freshness]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Gmail sync disabled for now to prevent duplicate counts with Autopilot
  // (Autopilot jobs are tracked directly in aa_autopilot_job)

  return (
    <ProgressProvider><div className={styles.minimal}>
      <ProgressHeader/>
      {error ? <p className={styles.errorBanner}>{error}</p> : null}

      <section className={styles.matchesSection}>
        <ApplicationAnalytics />
      </section>
      <QuestBoard/>
      <SearchIntelligence />

      <section className={styles.matchesSection}>
        <div className={styles.sectionHeader}>
          <h2>What happened to your applications</h2>
        </div>
        <ApplicationInsights />
      </section>

      <section className={styles.matchesSection}>
        <div className={styles.sectionHeader}>
          <h2>Top job matches</h2>
          <Link href={discoverHref(prefs)} className={styles.linkAction}>
            Open Job Scraper →
          </Link>
        </div>

        {loading ? (
          // Shaped like the match cards that are coming, so the grid is already
          // the right size when they land. `loading.tsx` covers the route
          // transition; this covers the data wait, which is the longer of the
          // two and the one that reads as slowness.
          <WorkspaceLoading label="Loading matches" shape="grid" rows={3} />
        ) : topJobs.length ? (
          <div className={styles.matchGrid}>
            {topJobs.slice(0, 5).map((job) => (
              <article key={job.id} className={styles.matchCard}>
                <div className={styles.matchMeta}>
                  <span>
                    {job.location || "United States"} · {job.freshness?.label || "Recently posted"}
                  </span>
                  <span
                    className={`${styles.matchRing} ${scoreTone(job.relevancyScore || 0)}`}
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
                    <button type="button" className={styles.btnPass}
                      aria-label={`Dismiss ${job.title} at ${job.companyName} from current matches`}
                      onClick={() => setTopJobs((current) => current.filter((item) => item.id !== job.id))}>
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
          // The shared empty-state component (components/ui/feedback.tsx) —
          // this replaced a hand-rolled paragraph that was the only place in
          // the app not using it, even though it fits this full-panel
          // context (icon + title + actions) exactly.
          <EmptyState
            title="No matches yet"
            description="Complete your profile so relevancy scoring has something to match against, then run a scrape to pull in postings."
            actions={
              <>
                <Link href="/profile" className="btn btn-secondary">
                  Complete your profile
                </Link>
                <Link href={discoverHref(prefs)} className="btn btn-primary">
                  Open Job Scraper →
                </Link>
              </>
            }
          />
        )}
      </section>

    </div></ProgressProvider>
  );
}
