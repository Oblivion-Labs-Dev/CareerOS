"use client";

import { StatePanel } from "@arsenal/ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson, postJson } from "@/lib/api";
import { AccomplishmentExplorer } from "./components/accomplishment-explorer";
import { AccomplishmentWorkspace } from "./components/accomplishment-workspace";
import { CorpusOverview } from "./components/corpus-overview";
import { CorpusSearchDialog } from "./components/corpus-search-dialog";
import { CorpusShell } from "./components/corpus-shell";
import { CreateAccomplishmentDialog } from "./components/create-accomplishment-dialog";
import { ComingSoonView } from "./components/coming-soon-view";
import {
  EvidenceView,
  InterviewView,
  MetricsView,
  SettingsView,
} from "./components/corpus-phase-one-views";
import { PREVIEW_PROFILE, PREVIEW_RECORDS } from "./corpus-fixtures";
import {
  getComingSoonFeature,
  isAdvancedCorpusView,
  isComingSoonFeatureId,
  isCorpusView,
  type ComingSoonFeatureId,
  type CorpusView,
} from "./corpus-navigation";
import { recordCorpusPerformance } from "./corpus-performance";
import { summarizeBulletReadiness } from "./corpus-quality";
import {
  applyRecordToLegacy,
  buildSearchIndex,
  createLegacyAccomplishmentDraft,
  normalizeAccomplishment,
  searchCorpus,
  summarizeCorpus,
  type CorpusProfile,
  type CorpusRecord,
  type NewAccomplishmentInput,
  type SearchCategory,
} from "./corpus-model";
import type { Accomplishment } from "./types";
import styles from "./resume-corpus.module.css";

interface ResumeCorpusClientProps {
  previewMode: boolean;
  initialView: CorpusView;
  initialRecordId?: string;
}

interface ProfileResponse {
  profile?: Record<string, unknown> & {
    fullName?: string;
    currentTitle?: string;
    targetRole?: string;
    yearsExperience?: string;
    primaryDomains?: string[];
  };
}

interface AccomplishmentsResponse {
  accomplishments?: Accomplishment[];
}

const EMPTY_PROFILE: CorpusProfile = {
  fullName: "Your career corpus",
  currentTitle: "Positioning not set",
  targetRole: "Target role not set",
  yearsExperience: "—",
  primaryDomains: [],
};

function profileWithDomains(profile: CorpusProfile, records: CorpusRecord[]): CorpusProfile {
  if (profile.primaryDomains.length > 0) return profile;
  const domainCounts = new Map<string, number>();
  for (const record of records) {
    for (const domain of record.domains) domainCounts.set(domain, (domainCounts.get(domain) ?? 0) + 1);
  }
  const primaryDomains = [...domainCounts.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, 3)
    .map(([domain]) => domain);
  return { ...profile, primaryDomains };
}

export function ResumeCorpusClient({ previewMode, initialView, initialRecordId }: ResumeCorpusClientProps) {
  const mountedAtRef = useRef(typeof performance === "undefined" ? 0 : performance.now());
  const previewLoadReportedRef = useRef(false);
  const [records, setRecords] = useState<CorpusRecord[]>(previewMode ? PREVIEW_RECORDS : []);
  const [profile, setProfile] = useState<CorpusProfile>(previewMode ? PREVIEW_PROFILE : EMPTY_PROFILE);
  const [profileSource, setProfileSource] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(!previewMode);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<CorpusView>(initialView);
  const [comingSoonFeatureId, setComingSoonFeatureId] = useState<ComingSoonFeatureId | undefined>(
    isAdvancedCorpusView(initialView) ? initialView : undefined,
  );
  const [selectedRecordId, setSelectedRecordId] = useState<string | undefined>(initialRecordId);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [searchResults, setSearchResults] = useState<ReturnType<typeof searchCorpus>>([]);

  const summary = useMemo(() => {
    const base = summarizeCorpus(records);
    const readiness = records.map(summarizeBulletReadiness);
    const average = (values: number[]) => values.length === 0 ? 0 : Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
    return {
      ...base,
      ready: readiness.filter((item) => item.overallStatus === "strong" || item.overallStatus === "interview-ready").length,
      resumeReadiness: average(readiness.map((item) => item.completionPercent)),
      interviewReadiness: average(readiness.map((item) => Math.round(((item.strongCount + item.interviewReadyCount) / Math.max(item.segments.reduce((sum, segment) => sum + segment.count, 0), 1)) * 100))),
      roastResistance: average(readiness.map((item) => item.roastResistance)),
    };
  }, [records]);
  const searchIndex = useMemo(() => buildSearchIndex(records), [records]);
  const selectedRecord = records.find((record) => record.id === selectedRecordId);
  const enrichedProfile = useMemo(() => profileWithDomains(profile, records), [profile, records]);
  const activeComingSoonFeature = useMemo(
    () => getComingSoonFeature(comingSoonFeatureId),
    [comingSoonFeatureId],
  );

  const loadCorpus = useCallback(async () => {
    if (previewMode) return;
    const startedAt = window.performance.now();
    setLoading(true);
    setLoadError(null);
    try {
      const [accomplishmentResponse, profileResponse] = await Promise.all([
        fetchJson<AccomplishmentsResponse>("/accomplishments", { revalidate: false }),
        fetchJson<ProfileResponse>("/profile", { revalidate: false }).catch(() => ({ profile: undefined })),
      ]);
      const nextRecords = (accomplishmentResponse.accomplishments ?? []).map(normalizeAccomplishment);
      setRecords(nextRecords);
      setProfile({
        fullName: profileResponse.profile?.fullName || EMPTY_PROFILE.fullName,
        currentTitle: profileResponse.profile?.currentTitle || EMPTY_PROFILE.currentTitle,
        targetRole: profileResponse.profile?.targetRole || EMPTY_PROFILE.targetRole,
        yearsExperience: profileResponse.profile?.yearsExperience || EMPTY_PROFILE.yearsExperience,
        primaryDomains: Array.isArray(profileResponse.profile?.primaryDomains)
          ? profileResponse.profile.primaryDomains.filter((value): value is string => typeof value === "string")
          : [],
      });
      setProfileSource(profileResponse.profile ?? {});
    } catch {
      setLoadError("CareerOS could not reach the corpus service. Nothing was replaced or cleared.");
    } finally {
      setLoading(false);
      recordCorpusPerformance("initial-load", window.performance.now() - startedAt, { previewMode: false });
    }
  }, [previewMode]);

  useEffect(() => {
    void loadCorpus();
  }, [loadCorpus]);

  useEffect(() => {
    if (!previewMode || previewLoadReportedRef.current) return;
    previewLoadReportedRef.current = true;
    window.requestAnimationFrame(() => recordCorpusPerformance("initial-load", window.performance.now() - mountedAtRef.current, { previewMode: true }));
  }, [previewMode]);

  useEffect(() => {
    const openSearch = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", openSearch);
    return () => window.removeEventListener("keydown", openSearch);
  }, []);

  useEffect(() => {
    const requestedView = new URL(window.location.href).searchParams.get("view");
    if (!isComingSoonFeatureId(requestedView)) return;
    setComingSoonFeatureId(requestedView);
    setActiveView(isCorpusView(requestedView) ? requestedView : "overview");
    setSelectedRecordId(undefined);
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const params = new URL(window.location.href).searchParams;
      const nextView = params.get("view");
      if (isComingSoonFeatureId(nextView)) {
        setComingSoonFeatureId(nextView);
        setActiveView(isCorpusView(nextView) ? nextView : "overview");
        setSelectedRecordId(undefined);
        return;
      }
      setComingSoonFeatureId(undefined);
      setActiveView(isCorpusView(nextView) ? nextView : "overview");
      setSelectedRecordId(params.get("record") ?? undefined);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!selectedRecordId || loading || records.some((record) => record.id === selectedRecordId)) return;
    setSelectedRecordId(undefined);
  }, [loading, records, selectedRecordId]);

  const updateUrl = (view: CorpusView | ComingSoonFeatureId, recordId?: string, replace = false, sectionId?: string) => {
    const url = new URL(window.location.href);
    if (view === "overview") url.searchParams.delete("view");
    else url.searchParams.set("view", view);
    if (recordId) url.searchParams.set("record", recordId);
    else url.searchParams.delete("record");
    url.hash = sectionId ? `corpus-section-${sectionId}` : "";
    const state = { view, recordId, sectionId };
    if (replace) window.history.replaceState(state, "", url);
    else window.history.pushState(state, "", url);
  };

  const resetWorkspaceScroll = () => {
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
  };

  const openComingSoon = (featureId: ComingSoonFeatureId) => {
    setComingSoonFeatureId(featureId);
    setActiveView(isCorpusView(featureId) ? featureId : "overview");
    setSelectedRecordId(undefined);
    updateUrl(featureId);
    resetWorkspaceScroll();
  };

  const navigate = (view: CorpusView) => {
    if (isAdvancedCorpusView(view)) {
      openComingSoon(view);
      return;
    }
    setComingSoonFeatureId(undefined);
    setActiveView(view);
    if (view !== "accomplishments") setSelectedRecordId(undefined);
    updateUrl(view);
    resetWorkspaceScroll();
  };

  const selectRecord = (record: CorpusRecord, sectionId?: string) => {
    setComingSoonFeatureId(undefined);
    setSelectedRecordId(record.id);
    setActiveView("accomplishments");
    updateUrl("accomplishments", record.id, false, sectionId);
    resetWorkspaceScroll();
  };

  const selectRecordById = (recordId: string, sectionId?: string) => {
    const record = records.find((candidate) => candidate.id === recordId);
    if (record) selectRecord(record, sectionId);
  };

  const backToExplorer = () => {
    setComingSoonFeatureId(undefined);
    setSelectedRecordId(undefined);
    setActiveView("accomplishments");
    updateUrl("accomplishments");
    resetWorkspaceScroll();
  };

  const commitRecord = useCallback(async (nextRecord: CorpusRecord) => {
    if (previewMode) {
      const saved = { ...nextRecord, updatedAt: new Date().toISOString() };
      setRecords((current) => current.map((record) => record.id === saved.id ? saved : record));
      return;
    }
    const legacy = applyRecordToLegacy(nextRecord);
    if (!legacy) throw new Error("This record does not have a legacy source payload.");
    const response = await postJson<{ accomplishment: Accomplishment }>("/accomplishments", { accomplishment: legacy });
    const saved = normalizeAccomplishment(response.accomplishment);
    setRecords((current) => current.map((record) => record.id === saved.id ? saved : record));
  }, [previewMode]);

  const createRecord = async (input: NewAccomplishmentInput) => {
    const draft = createLegacyAccomplishmentDraft(input);
    if (previewMode) {
      const record = normalizeAccomplishment(draft);
      setRecords((current) => [record, ...current]);
      selectRecord(record);
      return;
    }
    const response = await postJson<{ accomplishment: Accomplishment }>("/accomplishments", { accomplishment: draft });
    const record = normalizeAccomplishment(response.accomplishment);
    setRecords((current) => [record, ...current]);
    selectRecord(record);
  };

  const deleteRecord = async (recordId: string) => {
    if (!previewMode) await postJson(`/accomplishments/${recordId}`, {}, "DELETE");
    setRecords((current) => current.filter((record) => record.id !== recordId));
    backToExplorer();
  };

  const saveProfile = async (nextProfile: CorpusProfile) => {
    setProfile(nextProfile);
    if (previewMode) return;
    const nextSource = {
      ...profileSource,
      fullName: nextProfile.fullName,
      currentTitle: nextProfile.currentTitle,
      targetRole: nextProfile.targetRole,
      yearsExperience: nextProfile.yearsExperience,
      primaryDomains: nextProfile.primaryDomains,
    };
    const response = await postJson<ProfileResponse>("/profile", { profile: nextSource });
    setProfileSource(response.profile ?? nextSource);
  };

  const updateSearch = useCallback((query: string, category?: SearchCategory) => {
    const startedAt = window.performance.now();
    const nextResults = searchCorpus(searchIndex, query, category);
    setSearchResults(nextResults);
    recordCorpusPerformance("search", window.performance.now() - startedAt, { indexSize: searchIndex.length, resultCount: nextResults.length });
  }, [searchIndex]);

  let content;
  if (loading) {
    content = <StatePanel kind="loading" title="Loading your career corpus" description="Indexing accomplishments, evidence, and interview answers." />;
  } else if (loadError) {
    content = (
      <StatePanel
        kind="error"
        title="The corpus service is unavailable"
        description={loadError}
        action={
          <>
            <button type="button" className={styles.primaryButton} onClick={() => void loadCorpus()}>Try again</button>
            <a className={styles.quietButton} href="/resume-corpus?preview=1">Open sample workspace</a>
          </>
        }
      />
    );
  } else if (activeComingSoonFeature) {
    content = <ComingSoonView feature={activeComingSoonFeature} onNavigate={navigate} />;
  } else if (activeView === "overview") {
    content = <CorpusOverview profile={enrichedProfile} records={records} summary={summary} previewMode={previewMode} onNavigate={navigate} onSelectRecord={selectRecord} onCreate={() => setCreateOpen(true)} />;
  } else if (activeView === "accomplishments") {
    content = selectedRecord
      ? <AccomplishmentWorkspace key={selectedRecord.id} record={selectedRecord} previewMode={previewMode} onBack={backToExplorer} onCommit={commitRecord} onDelete={deleteRecord} />
      : <AccomplishmentExplorer records={records} onSelect={selectRecord} onCreate={() => setCreateOpen(true)} />;
  } else if (activeView === "interview") {
    content = <InterviewView records={records} onSelect={selectRecord} />;
  } else if (activeView === "metrics") {
    content = <MetricsView records={records} onSelect={selectRecord} />;
  } else if (activeView === "evidence") {
    content = <EvidenceView records={records} onSelect={selectRecord} />;
  } else if (activeView === "settings") {
    content = <SettingsView profile={profile} previewMode={previewMode} onProfileChange={setProfile} onSave={saveProfile} />;
  } else {
    content = null;
  }

  const statusLabel = loading ? "Indexing corpus" : loadError ? "Service unavailable" : previewMode ? "Preview data · local edits" : `${records.length} records indexed`;

  return (
    <>
      <CorpusShell
        activeView={activeView}
        activeComingSoon={activeComingSoonFeature}
        summary={summary}
        collapsed={railCollapsed}
        mobileOpen={mobileOpen}
        previewMode={previewMode}
        statusLabel={statusLabel}
        onCollapsedChange={setRailCollapsed}
        onMobileOpenChange={setMobileOpen}
        onNavigate={navigate}
        onOpenComingSoon={openComingSoon}
        onOpenSearch={() => setSearchOpen(true)}
        onCreate={() => setCreateOpen(true)}
      >
        {content}
      </CorpusShell>

      <CorpusSearchDialog
        open={searchOpen}
        results={searchResults}
        onClose={() => setSearchOpen(false)}
        onQueryChange={updateSearch}
        onSelectRecord={selectRecordById}
        onNavigate={navigate}
        onCreate={() => setCreateOpen(true)}
      />

      <CreateAccomplishmentDialog open={createOpen} onClose={() => setCreateOpen(false)} onCreate={createRecord} />
    </>
  );
}
