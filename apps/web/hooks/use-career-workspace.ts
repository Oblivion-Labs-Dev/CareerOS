"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { UserProfile } from "@career-os/core";
import { getClientApiBaseUrl } from "@/lib/api";
import { fetchCachedJson, getCachedStale } from "@/lib/client-fetch-cache";
import {
  profileCompleteness,
  readWorkspacePrefs,
  readWorkspaceSnapshot,
  writeWorkspacePrefs,
  writeWorkspaceSnapshot,
  type CareerWorkspacePrefs,
  type CareerWorkspaceSnapshot,
} from "@/lib/career-workspace";

type DiscoverStatsPayload = {
  totalJobs?: number;
  strongMatch?: number;
  scrapedAt?: string;
};

type TrackerPayload = {
  applications?: unknown[];
};

type ProfilePayload = {
  profile: Partial<UserProfile> | null;
};

const INITIAL_PREFS: CareerWorkspacePrefs = {
  searchQuery: "",
  location: "",
  roleFilter: "",
  freshness: "all",
};

export function useCareerWorkspace() {
  const api = getClientApiBaseUrl();
  const [snapshot, setSnapshot] = useState<CareerWorkspaceSnapshot | null>(null);
  const [prefs, setPrefs] = useState<CareerWorkspacePrefs>(INITIAL_PREFS);
  const [loading, setLoading] = useState(true);

  const loadWorkspace = useCallback(async (showLoading: boolean) => {
    if (showLoading) setLoading(true);
    try {
      const [profileResult, statsResult, trackerResult] = await Promise.allSettled([
        fetchCachedJson<ProfilePayload>(`${api}/profile`),
        fetchCachedJson<DiscoverStatsPayload>(`${api}/jobs/discover/stats`),
        fetchCachedJson<TrackerPayload>(`${api}/tracker/summary`),
      ]);

      const profile =
        profileResult.status === "fulfilled" ? profileResult.value.profile : getCachedStale<ProfilePayload>(`${api}/profile`)?.profile ?? null;
      const stats =
        statsResult.status === "fulfilled"
          ? statsResult.value
          : getCachedStale<DiscoverStatsPayload>(`${api}/jobs/discover/stats`) ?? {};
      const tracker =
        trackerResult.status === "fulfilled"
          ? trackerResult.value
          : getCachedStale<TrackerPayload>(`${api}/tracker/summary`) ?? {};

      const nextSnapshot: CareerWorkspaceSnapshot = {
        profile,
        discoverTotal: stats.totalJobs ?? 0,
        discoverStrongMatches: stats.strongMatch ?? 0,
        discoverScrapedAt: stats.scrapedAt,
        applicationsCount: tracker.applications?.length ?? 0,
        profileCompleteness: profileCompleteness(profile),
        loadedAt: new Date().toISOString(),
      };

      setSnapshot(nextSnapshot);
      writeWorkspaceSnapshot(nextSnapshot);

      const nextPrefs = readWorkspacePrefs();
      setPrefs(nextPrefs);
    } finally {
      setLoading(false);
    }
  }, [api]);

  const refresh = useCallback(async () => {
    await loadWorkspace(true);
  }, [loadWorkspace]);

  useEffect(() => {
    const cachedSnapshot = readWorkspaceSnapshot();
    setSnapshot(cachedSnapshot);
    setPrefs(readWorkspacePrefs());
    if (cachedSnapshot) setLoading(false);
    void loadWorkspace(!cachedSnapshot);
  }, [loadWorkspace]);

  const updatePrefs = useCallback((partial: Partial<CareerWorkspacePrefs>) => {
    const next = writeWorkspacePrefs(partial);
    setPrefs(next);
    return next;
  }, []);

  const displayName = useMemo(() => {
    const profile = snapshot?.profile;
    if (!profile) return "Your profile";
    return profile.fullName?.trim() || profile.firstName?.trim() || profile.targetRole?.trim() || "Your profile";
  }, [snapshot?.profile]);

  const targetLabel = useMemo(() => {
    const profile = snapshot?.profile;
    return profile?.targetRole?.trim() || profile?.currentTitle?.trim() || "Set a target role";
  }, [snapshot?.profile]);

  return {
    snapshot,
    prefs,
    loading,
    refresh,
    updatePrefs,
    displayName,
    targetLabel,
  };
}
