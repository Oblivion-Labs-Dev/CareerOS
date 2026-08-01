"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { UserProfile } from "@career-os/core";
import { getClientApiBaseUrl } from "@/lib/api";
import { fetchCachedJson, getCachedStale } from "@/lib/client-fetch-cache";
import {
  defaultLocationFromProfile,
  defaultSearchFromProfile,
  profileCompleteness,
  readWorkspacePrefs,
  readWorkspaceSnapshot,
  roleFilterFromProfile,
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

function mergePrefsWithProfile(profile: Partial<UserProfile> | null): CareerWorkspacePrefs {
  const stored = readWorkspacePrefs();
  return {
    searchQuery: stored.searchQuery,
    location: stored.location,
    roleFilter: stored.roleFilter,
    freshness: stored.freshness || "all",
  };
}

export function useCareerWorkspace() {
  const api = getClientApiBaseUrl();
  const cachedSnapshot = readWorkspaceSnapshot();

  const [snapshot, setSnapshot] = useState<CareerWorkspaceSnapshot | null>(cachedSnapshot);
  const [prefs, setPrefs] = useState<CareerWorkspacePrefs>(() =>
    mergePrefsWithProfile(cachedSnapshot?.profile ?? null),
  );
  const [loading, setLoading] = useState(() => !cachedSnapshot);

  const refresh = useCallback(async () => {
    setLoading(true);
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

      const nextPrefs = mergePrefsWithProfile(profile);
      setPrefs(nextPrefs);
      if (!readWorkspacePrefs().searchQuery) {
        writeWorkspacePrefs(nextPrefs);
      }
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
