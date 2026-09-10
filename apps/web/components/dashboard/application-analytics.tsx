"use client";

import { useEffect, useMemo, useState } from "react";
import { CountUp } from "@/components/count-up";
import { getAutopilotJobs } from "@/lib/application-assistant-api";
import { getClientApiBaseUrl } from "@/lib/api";
import { fetchCachedJson } from "@/lib/client-fetch-cache";
import {
  IconBolt,
  IconCheckCircle,
  IconClock,
  IconInbox,
  IconSend,
  IconTrendUp,
} from "@/components/application-assistant/autopilot/icons";
import styles from "./application-analytics.module.css";

const DAYS_SHOWN = 14;
const DAY_MS = 86_400_000;

function dayKey(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function jobTimestamp(job: any): number {
  const raw = job.submittedAt || job.updatedAt || job.queuedAt;
  const time = raw ? Date.parse(raw) : NaN;
  return Number.isNaN(time) ? NaN : time;
}

function appTimestamp(app: any): number {
  const raw = app.submittedAt || app.createdAt || app.updatedAt;
  const time = raw ? Date.parse(raw) : NaN;
  return Number.isNaN(time) ? NaN : time;
}

type TrackerSummaryResponse = {
  applications?: any[];
  autopilotSubmittedCount?: number;
  manualSubmittedCount?: number;
  totalSubmittedCount?: number;
};

export function ApplicationAnalytics({ refreshKey = 0 }: { refreshKey?: number }) {
  const [jobs, setJobs] = useState<any[] | null>(null);
  const [tracker, setTracker] = useState<TrackerSummaryResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    // 1. Fetch Autopilot submitted jobs
    getAutopilotJobs("SUBMITTED", 500)
      .then((res) => {
        if (!cancelled) setJobs(res.jobs || []);
      })
      .catch(() => {
        if (!cancelled) setJobs([]);
      });

    // 2. Fetch Tracker summary (includes Gmail manual applications and server-computed split counts)
    const api = getClientApiBaseUrl();
    fetchCachedJson<TrackerSummaryResponse>(`${api}/tracker/summary`, { staleMs: 5_000 })
      .then((data) => {
        if (!cancelled) setTracker(data || null);
      })
      .catch(() => {
        if (!cancelled) setTracker(null);
      });

    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const stats = useMemo(() => {
    if (jobs === null && tracker === null) return null;

    const autopilotList = jobs || [];
    // With Gmail sync disabled, use Autopilot jobs as clean source of truth to prevent double counting
    const autopilotCount =
      tracker?.autopilotSubmittedCount ??
      autopilotList.filter((j) => j.status === "SUBMITTED" || !j.status).length;
    const manualCount = 0;
    const total = autopilotCount;

    const today = startOfDay(new Date());

    // Only collect timestamps from verified autopilot jobs to eliminate double counts
    const autopilotTimestamps = autopilotList.map(jobTimestamp).filter((t) => !Number.isNaN(t));
    const allTimestamps = autopilotTimestamps;

    const buckets = new Map<string, number>();
    for (let i = DAYS_SHOWN - 1; i >= 0; i -= 1) {
      buckets.set(dayKey(new Date(today.getTime() - i * DAY_MS)), 0);
    }
    for (const t of allTimestamps) {
      const key = dayKey(startOfDay(new Date(t)));
      if (buckets.has(key)) buckets.set(key, (buckets.get(key) || 0) + 1);
    }

    const days = Array.from(buckets.entries()).map(([key, count]) => ({ key, count }));
    const max = Math.max(1, ...days.map((d) => d.count));

    const todayCount = buckets.get(dayKey(today)) || 0;
    const last7 = allTimestamps.filter((t) => t >= today.getTime() - 6 * DAY_MS).length;
    const prev7 = allTimestamps.filter(
      (t) => t >= today.getTime() - 13 * DAY_MS && t < today.getTime() - 6 * DAY_MS,
    ).length;
    const trendPct = prev7 > 0 ? Math.round(((last7 - prev7) / prev7) * 100) : last7 > 0 ? 100 : 0;
    const dailyAvg = Math.round((last7 / 7) * 10) / 10;

    return {
      days,
      max,
      total,
      autopilotCount,
      manualCount,
      todayCount,
      last7,
      trendPct,
      dailyAvg,
    };
  }, [jobs, tracker]);

  return (
    <div className={styles.wrap}>
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {/* Daily chart panel */}
        <div className={styles.chartPanel}>
          <div className={styles.chartHead}>
            <div>
              <h2 className={styles.chartTitle}>Applications per day</h2>
              <span className={styles.chartSubtitle} style={{ marginLeft: "0.5rem" }}>
                Autopilot submissions
              </span>
            </div>
            <span className={styles.chartSubtitle}>Last {DAYS_SHOWN} days{stats ? ` · ${stats.dailyAvg} / day this week` : ""}</span>
          </div>
          {!stats ? (
            <div className={styles.emptyChart}>Loading activity…</div>
          ) : stats.total === 0 ? (
            <div className={styles.emptyChart}>Your daily activity will appear after your first submission.</div>
          ) : (
            <div className={styles.chart}>
              {stats.days.map((day, index) => {
                const isToday = index === stats.days.length - 1;
                const heightPct = Math.round((day.count / stats.max) * 100);
                const label = new Date(`${day.key}T00:00:00`).toLocaleDateString(undefined, {
                  month: "numeric",
                  day: "numeric",
                });
                return (
                  <div
                    key={day.key}
                    className={`${styles.barCol} ${isToday ? styles["barCol--today"] : ""}`}
                    tabIndex={0}
                    aria-label={`${day.count} applications on ${label}`}
                    title={`${day.count} application${day.count === 1 ? "" : "s"} on ${label}`}
                  >
                    <span className={styles.barCount}>
                      {day.count > 0 ? <CountUp value={day.count} delayMs={index * 35} durationMs={800} /> : ""}
                    </span>
                    <div className={styles.barTrack}>
                      <div className={styles.bar} style={{ height: `${heightPct}%`, minHeight: day.count ? undefined : 0, animationDelay: `${index * 35}ms` }} />
                    </div>
                    <span className={styles.barLabel}>{label}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <div className={styles.statRow}>
          {/* Card 1: Total Summed Up */}
          <div className={styles.statTile} data-tone="accent">
            <span className={styles.statLabel}>
              <IconSend className="w-3.5 h-3.5" /> Total submitted
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}><CountUp value={stats ? stats.total : null} locale /></span>
            </div>
            <p className={styles.statSub}>
              {stats ? `${stats.autopilotCount} Autopilot verified` : "All-time applications"}
            </p>
          </div>

          {/* Card 2: Autopilot Applied */}
          <div className={styles.statTile} data-tone="violet">
            <span className={styles.statLabel}>
              <IconBolt className="w-3.5 h-3.5" /> CareerOS Autopilot
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}><CountUp value={stats ? stats.autopilotCount : null} locale delayMs={60} /></span>
            </div>
            <p className={styles.statSub}>Automated submissions</p>
          </div>

          {/* Card 3: Manual Gmail Synced */}
          <div className={styles.statTile} data-tone="cyan">
            <span className={styles.statLabel}>
              <IconInbox className="w-3.5 h-3.5" /> Manual (Gmail)
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}><CountUp value={stats ? stats.manualCount : null} locale delayMs={120} /></span>
            </div>
            <p className={styles.statSub}>Sync disabled (avoid duplicates)</p>
          </div>

          {/* Card 4: Today */}
          <div className={styles.statTile} data-tone="success">
            <span className={styles.statLabel}>
              <IconCheckCircle className="w-3.5 h-3.5" /> Today
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}><CountUp value={stats ? stats.todayCount : null} locale delayMs={180} /></span>
            </div>
            <p className={styles.statSub}>Applications submitted today</p>
          </div>

          {/* Card 5: This week */}
          <div className={styles.statTile} data-tone="amber">
            <span className={styles.statLabel}>
              <IconClock className="w-3.5 h-3.5" /> This week
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}><CountUp value={stats ? stats.last7 : null} locale delayMs={240} /></span>
              {stats && (
                <span
                  className={`${styles.statTrend} ${
                    stats.trendPct > 0
                      ? styles.statTrendUp
                      : stats.trendPct < 0
                      ? styles.statTrendDown
                      : styles.statTrendFlat
                  }`}
                >
                  {stats.trendPct > 0 ? "▲" : stats.trendPct < 0 ? "▼" : "–"}{" "}
                  <CountUp value={Math.abs(stats.trendPct)} suffix="%" locale delayMs={300} />
                </span>
              )}
            </div>
            <p className={styles.statSub}>vs. the previous 7 days</p>
          </div>
        </div>


      </div>
    </div>
  );
}
