"use client";

import { useCallback, useEffect, useState } from "react";
import { getDashboardStats, getStagedApplications } from "@/lib/application-assistant-api";

export type SidebarJobCounts = {
  jobScraper: number;
  applicationAssistant: number;
  reviewCenter: number;
};

const EMPTY_COUNTS: SidebarJobCounts = {
  jobScraper: 0,
  applicationAssistant: 0,
  reviewCenter: 0,
};

const INACTIVE_APP_STATUSES = new Set(["archived", "submitted_manually"]);

function activeApplicationCount(statusCounts: Record<string, number> | undefined): number {
  if (!statusCounts) return 0;
  return Object.entries(statusCounts).reduce(
    (sum, [status, count]) => sum + (INACTIVE_APP_STATUSES.has(status) ? 0 : count),
    0,
  );
}

export function formatNavCount(value: number): string {
  if (value >= 10_000) return `${Math.round(value / 1000)}k`;
  if (value >= 1000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return value.toLocaleString();
}

export function useSidebarJobCounts(pollMs = 30_000) {
  const [counts, setCounts] = useState<SidebarJobCounts | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [stats, staged] = await Promise.all([
        getDashboardStats(),
        // Count-only: the badge needs the total, not the ~4 MB review list.
        getStagedApplications({ limit: 0 }).catch(() => ({ staged: [], count: 0 })),
      ]);
      setCounts({
        jobScraper: stats.scraper?.pendingSync ?? 0,
        applicationAssistant: activeApplicationCount(stats.statusCounts),
        reviewCenter: staged.count ?? 0,
      });
    } catch {
      setCounts(null);
    }
  }, []);

  useEffect(() => {
    const poll = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    poll();
    const interval = setInterval(poll, pollMs);
    const onCountsChanged = () => void refresh();
    window.addEventListener("prep-started", onCountsChanged);
    window.addEventListener("careeros-job-counts-changed", onCountsChanged);
    document.addEventListener("visibilitychange", poll);
    return () => {
      clearInterval(interval);
      window.removeEventListener("prep-started", onCountsChanged);
      window.removeEventListener("careeros-job-counts-changed", onCountsChanged);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [pollMs, refresh]);

  return { counts: counts ?? EMPTY_COUNTS, loaded: counts !== null, refresh };
}

export function sidebarCountForHref(
  href: string,
  counts: SidebarJobCounts,
): number | null {
  if (href === "/jobs/discover") return counts.jobScraper;
  if (href === "/application-assistant") return counts.applicationAssistant;
  if (href === "/applications?tab=review") return counts.reviewCenter;
  return null;
}
