"use client";

import { useEffect, useMemo, useState } from "react";
import { getAutopilotJobs } from "@/lib/application-assistant-api";
import { IconCheckCircle, IconClock, IconSend, IconTrendUp } from "@/components/application-assistant/autopilot/icons";
import { AutopilotActivityCard } from "@/components/dashboard/autopilot-activity-card";
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

export function ApplicationAnalytics() {
  const [jobs, setJobs] = useState<any[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAutopilotJobs("SUBMITTED", 200)
      .then((res) => {
        if (!cancelled) setJobs(res.jobs || []);
      })
      .catch(() => {
        if (!cancelled) setJobs([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const stats = useMemo(() => {
    if (!jobs) return null;
    const today = startOfDay(new Date());
    const timestamps = jobs.map(jobTimestamp).filter((t) => !Number.isNaN(t));

    const buckets = new Map<string, number>();
    for (let i = DAYS_SHOWN - 1; i >= 0; i -= 1) {
      buckets.set(dayKey(new Date(today.getTime() - i * DAY_MS)), 0);
    }
    for (const t of timestamps) {
      const key = dayKey(startOfDay(new Date(t)));
      if (buckets.has(key)) buckets.set(key, (buckets.get(key) || 0) + 1);
    }

    const days = Array.from(buckets.entries()).map(([key, count]) => ({ key, count }));
    const max = Math.max(1, ...days.map((d) => d.count));

    const todayCount = buckets.get(dayKey(today)) || 0;
    const last7 = timestamps.filter((t) => t >= today.getTime() - 6 * DAY_MS).length;
    const prev7 = timestamps.filter(
      (t) => t >= today.getTime() - 13 * DAY_MS && t < today.getTime() - 6 * DAY_MS,
    ).length;
    const trendPct = prev7 > 0 ? Math.round(((last7 - prev7) / prev7) * 100) : last7 > 0 ? 100 : 0;
    const dailyAvg = Math.round((last7 / 7) * 10) / 10;

    return {
      days,
      max,
      total: jobs.length,
      todayCount,
      last7,
      trendPct,
      dailyAvg,
    };
  }, [jobs]);

  return (
    <div className={styles.wrap}>
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <div className={styles.statRow}>
          <div className={styles.statTile} data-tone="accent">
            <span className={styles.statLabel}>
              <IconSend className="w-3.5 h-3.5" /> Total submitted
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}>{stats ? stats.total : "—"}</span>
            </div>
            <p className={styles.statSub}>All-time Autopilot submissions</p>
          </div>

          <div className={styles.statTile} data-tone="success">
            <span className={styles.statLabel}>
              <IconCheckCircle className="w-3.5 h-3.5" /> Today
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}>{stats ? stats.todayCount : "—"}</span>
            </div>
            <p className={styles.statSub}>Applications submitted today</p>
          </div>

          <div className={styles.statTile} data-tone="violet">
            <span className={styles.statLabel}>
              <IconClock className="w-3.5 h-3.5" /> This week
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}>{stats ? stats.last7 : "—"}</span>
              {stats && (
                <span
                  className={`${styles.statTrend} ${
                    stats.trendPct > 0 ? styles.statTrendUp : stats.trendPct < 0 ? styles.statTrendDown : styles.statTrendFlat
                  }`}
                >
                  {stats.trendPct > 0 ? "▲" : stats.trendPct < 0 ? "▼" : "–"} {Math.abs(stats.trendPct)}%
                </span>
              )}
            </div>
            <p className={styles.statSub}>vs. the previous 7 days</p>
          </div>

          <div className={styles.statTile} data-tone="amber">
            <span className={styles.statLabel}>
              <IconTrendUp className="w-3.5 h-3.5" /> Daily average
            </span>
            <div className={styles.statValueRow}>
              <span className={styles.statValue}>{stats ? stats.dailyAvg : "—"}</span>
            </div>
            <p className={styles.statSub}>Applications per day (7d)</p>
          </div>
        </div>

        <div className={styles.chartPanel}>
          <div className={styles.chartHead}>
            <span className={styles.chartTitle}>Applications per day</span>
            <span className={styles.chartSubtitle}>Last {DAYS_SHOWN} days</span>
          </div>
          {!stats ? (
            <div className={styles.emptyChart}>Loading activity…</div>
          ) : stats.total === 0 ? (
            <div className={styles.emptyChart}>No submissions yet — start a run on the Autopilot page.</div>
          ) : (
            <div className={styles.chart}>
              {stats.days.map((day, index) => {
                const isToday = index === stats.days.length - 1;
                const heightPct = Math.max(4, Math.round((day.count / stats.max) * 100));
                const label = new Date(`${day.key}T00:00:00`).toLocaleDateString(undefined, {
                  month: "numeric",
                  day: "numeric",
                });
                return (
                  <div key={day.key} className={`${styles.barCol} ${isToday ? styles["barCol--today"] : ""}`} title={`${day.count} on ${label}`}>
                    <span className={styles.barCount}>{day.count > 0 ? day.count : ""}</span>
                    <div className={styles.barTrack}>
                      <div className={styles.bar} style={{ height: `${heightPct}%` }} />
                    </div>
                    <span className={styles.barLabel}>{label}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <div className={styles.breakdownCard}>
        <span className={styles.breakdownTitle}>Status breakdown</span>
        <AutopilotActivityCard />
      </div>
    </div>
  );
}
