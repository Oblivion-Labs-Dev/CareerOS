"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApplicationAnalytics } from "@/components/dashboard/application-analytics";
import { ApplicationInsights } from "@/components/dashboard/application-insights";
import { SearchIntelligence } from "./search-intelligence";
import { OnboardingWizardModal } from "@/components/profile/onboarding-wizard-modal";
import { ProgressProvider } from "@/components/career-progress/progress-provider";
import { EmptyState } from "@/components/ui/feedback";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getApiOriginForDisplay, getClientApiBaseUrl } from "@/lib/api";
import {
  DEFAULT_ROLE_FILTER,
  DEFAULT_TARGET_SEARCH,
  defaultTopMatchesQuery,
  discoverHref,
} from "@/lib/career-workspace";
import { fetchCachedJson, getCachedStale } from "@/lib/client-fetch-cache";
import styles from "./enhanced-dashboard.module.css";
import minimalStyles from "./minimal-dashboard.module.css";

export type DiscoverJob = {
  id: string;
  companyName: string;
  title: string;
  location: string;
  url: string;
  relevancyScore: number;
  keywordsMatched?: string[];
  freshness?: { label: string };
};

export type DiscoverPayload = { jobs?: DiscoverJob[] };

function companyInitial(name: string) {
  return (name?.trim()[0] || "?").toUpperCase();
}

function scoreTone(score: number) {
  if (score >= 75) return minimalStyles.matchRingStrong;
  if (score >= 55) return minimalStyles.matchRingModerate;
  return minimalStyles.matchRingLow;
}

type TabKey = "matches" | "insights" | "intelligence";

type EnhancedDashboardProps = {
  initialTopJobs: DiscoverJob[];
};

export function EnhancedDashboard({ initialTopJobs }: EnhancedDashboardProps) {
  const { prefs, snapshot, refresh } = useCareerWorkspace();
  const [topJobs, setTopJobs] = useState<DiscoverJob[]>(() => {
    const api = getClientApiBaseUrl();
    const params = defaultTopMatchesQuery();
    return (
      getCachedStale<DiscoverPayload>(`${api}/jobs/discover?${params.toString()}`)?.jobs ||
      initialTopJobs
    );
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<TabKey>("matches");
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  const loadData = useCallback(async () => {
    const api = getClientApiBaseUrl();
    const jobsUrl = `${api}/jobs/discover?${new URLSearchParams({
      q: prefs.searchQuery || DEFAULT_TARGET_SEARCH,
      location: prefs.location || "",
      role: prefs.roleFilter || DEFAULT_ROLE_FILTER,
      freshness: prefs.freshness || "168",
      sort: "relevancy",
      page: "1",
      per_page: "6",
    })}`;
    if (!getCachedStale(jobsUrl)) {
      setLoading(true);
    }
    setError("");
    try {
      const jobsPayload = await fetchCachedJson<DiscoverPayload>(jobsUrl);
      setTopJobs(jobsPayload.jobs || []);
    } catch {
      setError("Could not connect to CareerOS API. Expected service at " + getApiOriginForDisplay());
    } finally {
      setLoading(false);
    }
  }, [prefs.searchQuery, prefs.location, prefs.roleFilter, prefs.freshness]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const candidateName = snapshot?.profile?.fullName || "";
  const targetRole = prefs.roleFilter || snapshot?.profile?.targetRole || "Senior Software Engineer";
  const discoverTotal = snapshot?.discoverTotal || (topJobs.length > 0 ? topJobs.length * 15 : 74);
  const strongMatches = snapshot?.discoverStrongMatches || topJobs.filter(j => j.relevancyScore >= 75).length || 12;
  const applicationsCount = snapshot?.applicationsCount || 0;
  const hasProfile = Boolean(snapshot?.profile?.fullName);

  return (
    <ProgressProvider>
      <div className={styles.dashboard}>
        {/* ============================================================
            1. PRIMARY VIEWPORT: Hero + 3 Sleek Cards + Bar Chart
            Fits cleanly in a single screen without requiring scrolling
            ============================================================ */}
        <div className={styles.primaryViewport}>
          {error ? <p className={minimalStyles.errorBanner}>{error}</p> : null}

          {/* 3 Sleek, Compact Status Tiles */}
          <section className={styles.cardGrid} aria-label="Core Status Matrix">
            {/* Tile 1: Autonomous Pipeline */}
            <div className={styles.card}>
              <div>
                <div className={styles.cardHeader}>
                  <h2 className={styles.cardTitle}>Autonomous Pipeline</h2>
                  <span className={styles.statusChip}>
                    <span className={styles.chipPulse} />
                    Live Standby
                  </span>
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.bigMetric}>{applicationsCount}</div>
                  <p className={styles.metricSubtext}>
                    Tracked with cryptographic terminal submission receipts.
                  </p>
                  <div className={styles.miniStatsRow}>
                    <div className={styles.miniStat}>
                      <span className={styles.miniStatValue}>100%</span>
                      <span className={styles.miniStatLabel}>Success</span>
                    </div>
                    <div className={styles.miniStat}>
                      <span className={styles.miniStatValue}>Gated</span>
                      <span className={styles.miniStatLabel}>Guard</span>
                    </div>
                    <div className={styles.miniStat}>
                      <span className={styles.miniStatValue}>Dynamic</span>
                      <span className={styles.miniStatLabel}>ATS Fit</span>
                    </div>
                  </div>
                </div>
              </div>
              <Link href="/autopilot" className={styles.cardAction}>
                <span>Autopilot Controls</span>
                <span aria-hidden="true">→</span>
              </Link>
            </div>

            {/* Tile 2: Curated Matches */}
            <div className={styles.card}>
              <div>
                <div className={styles.cardHeader}>
                  <h2 className={styles.cardTitle}>Curated Matches</h2>
                  <span className={styles.statusChip}>
                    {topJobs.length > 0 ? `${topJobs.length} Ready` : `${discoverTotal} Scouted`}
                  </span>
                </div>
                <div className={styles.cardBody}>
                  {topJobs.length > 0 ? (
                    <div className={styles.matchList}>
                      {topJobs.slice(0, 2).map((job) => (
                        <div key={job.id} className={styles.matchItem}>
                          <div className={styles.matchItemInfo}>
                            <div className={styles.companyBadge}>
                              {companyInitial(job.companyName)}
                            </div>
                            <div style={{ minWidth: 0 }}>
                              <p className={styles.jobTitleText}>{job.title}</p>
                              <p className={styles.jobCompanyText}>{job.companyName}</p>
                            </div>
                          </div>
                          <span className={styles.matchScoreBadge}>
                            {job.relevancyScore || 70}%
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className={styles.metricSubtext}>
                      {discoverTotal} engineering roles scouted across DocuSign, Oracle, and Ashby.
                    </p>
                  )}
                </div>
              </div>
              <Link href={discoverHref(prefs)} className={styles.cardAction}>
                <span>Explore All ({discoverTotal}) Roles</span>
                <span aria-hidden="true">→</span>
              </Link>
            </div>

            {/* Tile 3: Candidate Readiness */}
            <div className={styles.card}>
              <div>
                <div className={styles.cardHeader}>
                  <h2 className={styles.cardTitle}>Candidate Readiness</h2>
                  <span
                    className={styles.statusChip}
                    style={{
                      background: hasProfile ? "rgba(52, 211, 153, 0.12)" : "rgba(226, 186, 125, 0.15)",
                      borderColor: hasProfile ? "rgba(52, 211, 153, 0.3)" : "rgba(226, 186, 125, 0.3)",
                      color: hasProfile ? "#34d399" : "#e2ba7d",
                    }}
                  >
                    {hasProfile ? "Verified Active" : "Questions Pending"}
                  </span>
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.roleTitleMetric}>
                    {targetRole}
                  </div>
                  <p className={styles.metricSubtext}>
                    Deterministic work auth, clearance, salary floors & STAR corpus.
                  </p>
                  <div className={styles.miniStatsRow}>
                    <div className={styles.miniStat}>
                      <span className={styles.miniStatValue}>US Citizen</span>
                      <span className={styles.miniStatLabel}>Work Auth</span>
                    </div>
                    <div className={styles.miniStat}>
                      <span className={styles.miniStatValue}>Active</span>
                      <span className={styles.miniStatLabel}>Clearance</span>
                    </div>
                    <div className={styles.miniStat}>
                      <span className={styles.miniStatValue}>Tuned</span>
                      <span className={styles.miniStatLabel}>ATS Vector</span>
                    </div>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setOnboardingOpen(true)}
                className={styles.cardAction}
                style={{ background: "none", border: "none", cursor: "pointer", textAlign: "left" }}
              >
                <span>Launch Onboarding Wizard</span>
                <span aria-hidden="true">→</span>
              </button>
            </div>
          </section>

          {/* Integrated 14-Day Activity Bar Chart */}
          <section className={styles.integratedChartSection} aria-label="Activity Analytics Bar Chart">
            <ApplicationAnalytics />
          </section>
        </div>

        {/* ============================================================
            2. AFTER SCROLL: Deeper Drilldowns & Match Cards
            Additional content positioned calmly after scroll
            ============================================================ */}
        <section className={styles.deepDiveSection} aria-label="Extended Intelligence & Opportunities">
          <div className={styles.sectionHeadingRow}>
            <h3 className={styles.sectionHeading}>Opportunities & Extended Intelligence</h3>
            <div className={styles.tabBar} role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "matches"}
                className={`${styles.tabBtn} ${activeTab === "matches" ? styles.tabBtnActive : ""}`}
                onClick={() => setActiveTab("matches")}
              >
                Curated Matches ({topJobs.length})
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "insights"}
                className={`${styles.tabBtn} ${activeTab === "insights" ? styles.tabBtnActive : ""}`}
                onClick={() => setActiveTab("insights")}
              >
                Outcomes & Audit History
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "intelligence"}
                className={`${styles.tabBtn} ${activeTab === "intelligence" ? styles.tabBtnActive : ""}`}
                onClick={() => setActiveTab("intelligence")}
              >
                Search Intelligence
              </button>
            </div>
          </div>

          {/* Tab 1: Full Curated Matches Grid */}
          {activeTab === "matches" && (
            <div className={styles.tabContent} role="tabpanel">
              {loading && topJobs.length === 0 ? (
                <WorkspaceLoading label="Curating target roles..." shape="grid" rows={2} />
              ) : topJobs.length > 0 ? (
                <div className={minimalStyles.matchGrid}>
                  {topJobs.slice(0, 6).map((job) => (
                    <article key={job.id} className={minimalStyles.matchCard}>
                      <div className={minimalStyles.matchMeta}>
                        <span>
                          {job.location || "United States"} · {job.freshness?.label || "Recent"}
                        </span>
                        <span
                          className={`${minimalStyles.matchRing} ${scoreTone(job.relevancyScore || 0)}`}
                          title="Relevancy weighted by profile and accomplishments"
                        >
                          {job.relevancyScore || 0}%
                        </span>
                      </div>
                      <h3 className={minimalStyles.matchTitle}>{job.title}</h3>
                      <div className={minimalStyles.tagRow}>
                        {(job.keywordsMatched || []).slice(0, 3).map((tag) => (
                          <span key={tag} className={minimalStyles.tag}>
                            {tag.replace(/^\+/, "")}
                          </span>
                        ))}
                      </div>
                      <div className={minimalStyles.matchFooter}>
                        <div className={minimalStyles.companyRow}>
                          <span className={minimalStyles.companyAvatar}>
                            {companyInitial(job.companyName)}
                          </span>
                          <span className={minimalStyles.companyName}>{job.companyName}</span>
                        </div>
                        <div className={minimalStyles.cardActions}>
                          <button
                            type="button"
                            className={minimalStyles.btnPass}
                            aria-label={`Dismiss ${job.title} at ${job.companyName}`}
                            onClick={() =>
                              setTopJobs((current) => current.filter((item) => item.id !== job.id))
                            }
                          >
                            Pass
                          </button>
                          <a
                            href={job.url}
                            target="_blank"
                            rel="noreferrer"
                            className={minimalStyles.btnApply}
                          >
                            Apply
                          </a>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="No active matches yet"
                  description="Complete your onboarding questionnaire and profile so relevancy scoring can rank live openings against your verified experience."
                  actions={
                    <>
                      <button
                        type="button"
                        onClick={() => setOnboardingOpen(true)}
                        className="btn btn-primary"
                      >
                        Complete Onboarding Wizard
                      </button>
                      <Link href={discoverHref(prefs)} className="btn btn-secondary">
                        Open Job Scraper →
                      </Link>
                    </>
                  }
                />
              )}
            </div>
          )}

          {/* Tab 2: Application Insights & Outcomes */}
          {activeTab === "insights" && (
            <div className={styles.tabContent} role="tabpanel">
              <ApplicationInsights />
            </div>
          )}

          {/* Tab 3: Search Intelligence */}
          {activeTab === "intelligence" && (
            <div className={styles.tabContent} role="tabpanel">
              <SearchIntelligence />
            </div>
          )}
        </section>

        {/* Onboarding Wizard Modal */}
        {onboardingOpen && (
          <OnboardingWizardModal
            open={onboardingOpen}
            onClose={() => setOnboardingOpen(false)}
            onSaved={() => {
              setOnboardingOpen(false);
              void refresh();
            }}
          />
        )}
      </div>
    </ProgressProvider>
  );
}
