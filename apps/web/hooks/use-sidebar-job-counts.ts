"use client";

import { useCallback, useEffect, useState } from "react";
import { getDashboardStats } from "@/lib/application-assistant-api";

export type SidebarJobCounts = {
  jobScraper: number;
  applicationAssistant: number;
};

const EMPTY_COUNTS: SidebarJobCounts = {
  jobScraper: 0,
  applicationAssistant: 0,
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
      const stats = await getDashboardStats();
      setCounts({
        jobScraper: stats.scraper?.pendingSync ?? 0,
        applicationAssistant: activeApplicationCount(stats.statusCounts),
      });
    } catch {
      setCounts(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = setInterval(() => void refresh(), pollMs);
    const onCountsChanged = () => void refresh();
    window.addEventListener("qwen-prep-started", onCountsChanged);
    window.addEventListener("careeros-job-counts-changed", onCountsChanged);
    return () => {
      clearInterval(interval);
      window.removeEventListener("qwen-prep-started", onCountsChanged);
      window.removeEventListener("careeros-job-counts-changed", onCountsChanged);
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
  return null;
}
