"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApplicationAnalytics } from "@/components/dashboard/application-analytics";
import { ApplicationInsights } from "@/components/dashboard/application-insights";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getApiOriginForDisplay, getClientApiBaseUrl, postJson } from "@/lib/api";
import { discoverHref } from "@/lib/career-workspace";
import { fetchCachedJson, getCachedStale, invalidateCachedByPrefix } from "@/lib/client-fetch-cache";
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

/** Only the part of the tracker payload this page still reads. */
type TrackerSnapshot = { applications?: { status?: string }[] };

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
  const [gmailSync, setGmailSync] = useState<{ busy: boolean; note: string }>({ busy: false, note: "" });
  const [refreshKey, setRefreshKey] = useState(0);


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
      setError("Could not load dashboard. Start the API at " + getApiOriginForDisplay());
    } finally {
      setLoading(false);
    }
  }, [prefs.searchQuery, prefs.location, prefs.roleFilter, prefs.freshness]);

  const syncGmail = useCallback(async () => {
    setGmailSync({ busy: true, note: "" });
    try {
      const res = await postJson<{ success: boolean; added?: number; addedCareeros?: number; addedManual?: number; skipped?: number; reason?: string }>(
        "/tracker/sync-gmail",
        {},
      );
      if (!res.success) {
        setGmailSync({ busy: false, note: res.reason || "Gmail sync unavailable" });
        return;
      }
      const parts: string[] = [];
      if (res.addedCareeros) parts.push(`${res.addedCareeros} CareerOS`);
      if (res.addedManual) parts.push(`${res.addedManual} manual`);
      setGmailSync({
        busy: false,
        note: res.added
          ? `Added ${res.added} application${res.added === 1 ? "" : "s"} from Gmail${parts.length ? ` (${parts.join(", ")})` : ""}.`
          : "No new applications found in Gmail.",
      });
      invalidateCachedByPrefix(`${getClientApiBaseUrl()}/tracker`);
      setRefreshKey((k) => k + 1);
      await loadData();
    } catch (err) {
      setGmailSync({ busy: false, note: err instanceof Error ? err.message : "Gmail sync failed" });
    }
  }, [loadData]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Pull in applications submitted outside CareerOS once per browser session —
  // an IMAP round trip is too slow to repeat on every dashboard visit.
  useEffect(() => {
    const KEY = "careeros-gmail-synced-v1";
    try {
      if (sessionStorage.getItem(KEY)) return;
      sessionStorage.setItem(KEY, "1");
    } catch {
      return;
    }
    void syncGmail();
  }, [syncGmail]);

  return (
    <div className={styles.minimal}>
      {error ? <p className={styles.errorBanner}>{error}</p> : null}

      <section className={styles.matchesSection}>
        <div className={styles.sectionHeader}>
          <h2>Application analytics</h2>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
            {gmailSync.note ? <span className={styles.muted}>{gmailSync.note}</span> : null}
            <button
              type="button"
              className={styles.btnPass}
              onClick={() => void syncGmail()}
              disabled={gmailSync.busy}
              title="Scan Gmail for applications you submitted outside CareerOS and track them here"
            >
              {gmailSync.busy ? "Syncing Gmail…" : "Sync Gmail"}
            </button>
            <Link href="/applications?tab=autopilot" className={styles.linkAction}>
              Open Autopilot →
            </Link>
          </div>
        </div>
        <ApplicationAnalytics refreshKey={refreshKey} />
      </section>

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
          <p className={styles.muted}>Loading matches…</p>
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

    </div>
  );
}
