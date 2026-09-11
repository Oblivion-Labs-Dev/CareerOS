"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BrowseFilterControls, EMPTY_BROWSE, type BrowseOptions, type BrowseSelection } from "./browse-filter-controls";
import { ChoiceGroup } from "@/components/ui/choice-group";
import type { DiscoverJob } from "./discover-job";
import { DiscoverJobCard } from "./discover-job-card";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import styles from "./browse-jobs.module.css";
import { useCareerWorkspace } from "@/hooks/use-career-workspace";
import { getClientApiBaseUrl } from "@/lib/api";
import {
  approvePreflightSubmission,
  getScraperSyncStatus,
  importScraperJob,
  qwenPrepareJob,
} from "@/lib/application-assistant-api";
import { usePrepQueueStatus } from "@/hooks/use-prep-queue-status";
import { fetchCachedJson, invalidateCachedByPrefix } from "@/lib/client-fetch-cache";
import { isDiscoverCacheFresh, readDiscoverCache, writeDiscoverCache } from "@/lib/job-discover-cache";
import { DiscoverTriageBar } from "@/components/jobs/discover-triage-bar";
import { JobMatchGapPanel, type JobGapAnalysis, type JobGapPanelJob } from "@/components/jobs/job-match-gap-panel";
import {
  matchesTriageFilters,
  type AtsSource,
  type Seniority,
} from "@/lib/inbox-triage";



type DiscoverResponse = {
  success: boolean;
  jobs: DiscoverJob[];
  total: number;
  indexedTotal?: number;
  assistantTotal?: number;
  page: number;
  perPage?: number;
  totalPages: number;
  scrapedAt?: string;
  indexedCompanies?: number;
  status?: { running: boolean; progress: string; lastResult: string };
};

type DiscoverGlobalStats = {
  totalJobs: number;
  indexedCompanies: number;
  strongMatch: number;
  moderateMatch: number;
  fresh48h: number;
  scrapedAt?: string;
};

type LocationOption = {
  value: string;
  label: string;
  count: number;
};

type StatusResponse = {
  success: boolean;
  running: boolean;
  progress: string;
  lastResult: string;
  indexedJobs?: number;
  strongMatches?: number;
  moderateMatches?: number;
  freshMatches?: number;
  indexedCompanies?: number;
  qwenRescore?: {
    running: boolean;
    progress: string;
    lastResult: string;
    scored: number;
    total: number;
  };
  postRescore?: {
    running: boolean;
    phase: string;
    progress: string;
    lastResult: string;
    processed: number;
    total: number;
    qwenRescore?: StatusResponse["qwenRescore"];
  };
  tier1Rescore?: {
    running: boolean;
    progress: string;
    lastResult: string;
    processed: number;
    total: number;
  };
};

type LiveCounts = {
  indexed: number;
  strong: number;
  moderate: number;
  fresh: number;
  companies: number;
};

function liveCountsFromStatus(status: StatusResponse): LiveCounts | null {
  if (status.indexedJobs == null) return null;
  return {
    indexed: status.indexedJobs,
    strong: status.strongMatches ?? 0,
    moderate: status.moderateMatches ?? 0,
    fresh: status.freshMatches ?? 0,
    companies: status.indexedCompanies ?? 0,
  };
}

type FreshnessFilter = "all" | "12" | "24" | "48" | "72" | "168" | "336" | "720";
type SponsorshipFilter = "all" | "likely" | "unlikely" | "friendly";
type ScrapeMode = "ats" | "bigtech" | "apify" | "all";
type SortFilter = "relevancy" | "date" | "company";

const POSTED_AGO_OPTIONS: { value: FreshnessFilter; label: string }[] = [
  { value: "all", label: "Any time" },
  { value: "12", label: "Last 12 hours" },
  { value: "24", label: "Last 24 hours" },
  { value: "48", label: "Last 2 days" },
  { value: "72", label: "Last 3 days" },
  { value: "168", label: "Last 7 days" },
  { value: "336", label: "Last 14 days" },
  { value: "720", label: "Last 30 days" },
];



const TOP_50_COMPANIES = [
  "Stripe", "OpenAI", "Anthropic", "Databricks", "Datadog", "Cloudflare", "Figma", "Airbnb",
  "Vercel", "Supabase", "Notion", "Brex", "Ramp", "Snowflake", "Reddit", "Discord",
  "SpaceX", "Anduril", "Spotify", "Netflix", "Palantir", "Atlassian", "Grammarly", "Plaid",
  "Deel", "Sentry", "Salesforce", "Nvidia", "Zoom", "Google", "Amazon", "Microsoft",
  "Meta", "Apple", "Uber", "DoorDash", "Pinterest", "Roblox", "Coinbase", "Block",
  "Robinhood", "Linear", "Miro", "Canva", "Postman", "HubSpot", "GitLab", "Docker", "Snyk", "Twilio"
];

const LOCATION_QUICK_PICKS = [
  "United States",
  "Remote US",
  "California",
  "Washington",
  "New York",
  "Texas",
  "Massachusetts",
  "Colorado",
  "Illinois",
  "Seattle",
  "San Francisco",
  "Austin",
];

function postedAgoLabel(value: FreshnessFilter) {
  return POSTED_AGO_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

function formatRefreshed(value?: string) {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatScrapeProgress(raw: string, indexed?: number) {
  const boards = raw.replace("ATS companies", "ATS boards").replace("companies", "boards");
  if (indexed != null && indexed > 0) {
    return `${boards} · ${indexed.toLocaleString()} roles saved`;
  }
  return boards;
}

function formatLocationOption(label: string, count: number) {
  const short = label.length > 52 ? `${label.slice(0, 49)}…` : label;
  return `${short} (${count.toLocaleString()})`;
}

type ComboboxOption = {
  value: string;
  label?: string;
  sublabel?: string;
};

type SearchableComboboxProps = {
  name: string;
  value: string;
  onChange: (val: string) => void;
  options: ComboboxOption[];
  placeholder: string;
  required?: boolean;
  style?: React.CSSProperties;
};

function SearchableCombobox({
  name,
  value,
  onChange,
  options,
  placeholder,
  required = false,
  style,
}: SearchableComboboxProps) {
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const filteredOptions = useMemo(() => {
    const query = value.trim().toLowerCase();
    if (!query) return options;
    return options.filter(
      (opt) =>
        opt.value.toLowerCase().includes(query) ||
        (opt.label && opt.label.toLowerCase().includes(query))
    );
  }, [options, value]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div
      ref={containerRef}
      className="cos-combobox-wrap"
      style={{ position: "relative", width: "100%", ...style }}
    >
      <input
        name={name}
        type="text"
        value={value}
        required={required}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setHighlightIndex(0);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setHighlightIndex((prev) => Math.min(prev + 1, Math.max(0, filteredOptions.length - 1)));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHighlightIndex((prev) => Math.max(prev - 1, 0));
          } else if (e.key === "Enter" && open && filteredOptions[highlightIndex]) {
            e.preventDefault();
            onChange(filteredOptions[highlightIndex].value);
            setOpen(false);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        className="cos-combobox-input"
        style={{ paddingRight: required ? "1.75rem" : "0.75rem" }}
        autoComplete="off"
      />
      {required ? (
        <span
          className="cos-required-badge"
          style={{
            position: "absolute",
            right: "0.65rem",
            top: "50%",
            transform: "translateY(-50%)",
            color: "#ef4444",
            fontWeight: 700,
            fontSize: "1rem",
            pointerEvents: "none",
            lineHeight: 1,
          }}
          title="Required field"
        >
          *
        </span>
      ) : null}

      {open && filteredOptions.length > 0 ? (
        <ul
          className="cos-combobox-dropdown"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            maxHeight: "220px",
            overflowY: "auto",
            backgroundColor: "#11161d",
            border: "1px solid rgba(166, 181, 201, 0.22)",
            borderRadius: "10px",
            boxShadow: "0 12px 32px rgba(0, 0, 0, 0.5)",
            zIndex: 100,
            padding: "0.35rem",
            margin: 0,
            listStyle: "none",
          }}
        >
          {filteredOptions.slice(0, 40).map((opt, idx) => {
            const isHighlighted = idx === highlightIndex;
            return (
              <li
                key={opt.value}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onChange(opt.value);
                  setOpen(false);
                }}
                onMouseEnter={() => setHighlightIndex(idx)}
                style={{
                  padding: "0.45rem 0.65rem",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "0.875rem",
                  color: isHighlighted ? "#62ddc5" : "#f5f8fb",
                  backgroundColor: isHighlighted ? "#19212b" : "transparent",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  transition: "background-color 0.12s ease",
                }}
              >
                <span>{opt.label ?? opt.value}</span>
                {opt.sublabel ? (
                  <span style={{ fontSize: "0.75rem", color: "#9aa8b9", marginLeft: "0.5rem" }}>
                    {opt.sublabel}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

type MultiSelectComboboxProps = {
  name: string;
  selectedValues: string[];
  onChange: (vals: string[]) => void;
  options: ComboboxOption[];
  placeholder: string;
  required?: boolean;
  style?: React.CSSProperties;
};

function MultiSelectCombobox({
  name,
  selectedValues,
  onChange,
  options,
  placeholder,
  required = false,
  style,
}: MultiSelectComboboxProps) {
  const [inputValue, setInputValue] = useState("");
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedSet = useMemo(
    () => new Set(selectedValues.map((v) => v.toLowerCase())),
    [selectedValues]
  );

  const filteredOptions = useMemo(() => {
    const query = inputValue.trim().toLowerCase();
    const available = options.filter((opt) => !selectedSet.has(opt.value.toLowerCase()));
    if (!query) return available;
    return available.filter(
      (opt) =>
        opt.value.toLowerCase().includes(query) ||
        (opt.label && opt.label.toLowerCase().includes(query))
    );
  }, [options, inputValue, selectedSet]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function addValue(val: string) {
    const clean = val.trim();
    if (!clean) return;
    if (!selectedValues.some((v) => v.toLowerCase() === clean.toLowerCase())) {
      onChange([...selectedValues, clean]);
    }
    setInputValue("");
    setOpen(false);
  }

  function removeValue(val: string) {
    onChange(selectedValues.filter((v) => v.toLowerCase() !== val.toLowerCase()));
  }

  return (
    <div
      ref={containerRef}
      className="cos-multiselect-combobox-wrap"
      style={{ position: "relative", width: "100%", ...style }}
    >
      <input type="hidden" name={name} value={selectedValues.join(", ")} />
      <div
        className="cos-multiselect-box"
        onClick={() => setOpen(true)}
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "0.35rem",
          minHeight: "2.6rem",
          padding: "0.3rem 0.5rem",
          backgroundColor: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--cos-radius-control)",
          cursor: "text",
          position: "relative",
        }}
      >
        {selectedValues.map((val) => (
          <span
            key={val}
            className="cos-location-tag-pill"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.25rem",
              padding: "0.15rem 0.45rem",
              backgroundColor: "rgba(98, 221, 197, 0.15)",
              border: "1px solid rgba(98, 221, 197, 0.35)",
              color: "#62ddc5",
              borderRadius: "6px",
              fontSize: "0.8rem",
              fontWeight: 600,
            }}
          >
            {val}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                removeValue(val);
              }}
              style={{
                background: "none",
                border: 0,
                color: "#62ddc5",
                cursor: "pointer",
                padding: 0,
                fontSize: "0.85rem",
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          </span>
        ))}

        <input
          type="text"
          value={inputValue}
          placeholder={selectedValues.length === 0 ? placeholder : "Add location…"}
          onChange={(e) => {
            setInputValue(e.target.value);
            setOpen(true);
            setHighlightIndex(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (open && filteredOptions[highlightIndex]) {
                addValue(filteredOptions[highlightIndex].value);
              } else if (inputValue.trim()) {
                addValue(inputValue);
              }
            } else if (e.key === "Backspace" && !inputValue && selectedValues.length > 0) {
              removeValue(selectedValues[selectedValues.length - 1]);
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              setOpen(true);
              setHighlightIndex((prev) => Math.min(prev + 1, Math.max(0, filteredOptions.length - 1)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setHighlightIndex((prev) => Math.max(prev - 1, 0));
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          style={{
            flex: 1,
            minWidth: "120px",
            background: "transparent",
            border: 0,
            color: "var(--text)",
            fontSize: "0.875rem",
            outline: "none",
            padding: "0.2rem",
          }}
          autoComplete="off"
        />

        {required && selectedValues.length === 0 && !inputValue ? (
          <span
            style={{
              position: "absolute",
              right: "0.65rem",
              top: "50%",
              transform: "translateY(-50%)",
              color: "#ef4444",
              fontWeight: 700,
              fontSize: "1rem",
              pointerEvents: "none",
            }}
            title="Required field"
          >
            *
          </span>
        ) : null}
      </div>

      {open && filteredOptions.length > 0 ? (
        <ul
          className="cos-combobox-dropdown"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            maxHeight: "220px",
            overflowY: "auto",
            backgroundColor: "#11161d",
            border: "1px solid rgba(166, 181, 201, 0.22)",
            borderRadius: "10px",
            boxShadow: "0 12px 32px rgba(0, 0, 0, 0.5)",
            zIndex: 100,
            padding: "0.35rem",
            margin: 0,
            listStyle: "none",
          }}
        >
          {filteredOptions.slice(0, 40).map((opt, idx) => {
            const isHighlighted = idx === highlightIndex;
            return (
              <li
                key={opt.value}
                onMouseDown={(e) => {
                  e.preventDefault();
                  addValue(opt.value);
                }}
                onMouseEnter={() => setHighlightIndex(idx)}
                style={{
                  padding: "0.45rem 0.65rem",
                  borderRadius: "6px",
                  cursor: "pointer",
                  fontSize: "0.875rem",
                  color: isHighlighted ? "#62ddc5" : "#f5f8fb",
                  backgroundColor: isHighlighted ? "#19212b" : "transparent",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  transition: "background-color 0.12s ease",
                }}
              >
                <span>{opt.label ?? opt.value}</span>
                {opt.sublabel ? (
                  <span style={{ fontSize: "0.75rem", color: "#9aa8b9", marginLeft: "0.5rem" }}>
                    {opt.sublabel}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

export function JobDiscoverDashboard() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { prefs, updatePrefs, snapshot, refresh: refreshWorkspace } = useCareerWorkspace();
  const [facets,setFacets] = useState({specialties:[] as string[],seniorities:[] as string[],workModes:[] as string[],experience:"",companies:[] as string[]});
  const [filterOptions,setFilterOptions] = useState<BrowseOptions>({titles:["Software Engineer","Product Manager","Business Intelligence Engineer","BIE","Technical Program Manager","Product Designer","Data Analyst"],companies:[],specialties:[]});
  useEffect(()=>{fetch(`${getClientApiBaseUrl()}/jobs/discover/filter-options`).then(async r=>{if(!r.ok)throw new Error();return r.json();}).then(setFilterOptions).catch(()=>{});},[]);
  const [q, setQ] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [selectedLocations, setSelectedLocations] = useState<string[]>([]);
  const [role, setRole] = useState("");
  const [freshness, setFreshness] = useState<FreshnessFilter>("all");
  const [sponsorship, setSponsorship] = useState<SponsorshipFilter>("all");
  const [sort, setSort] = useState<SortFilter>("relevancy");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<DiscoverResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState("");
  const [liveCounts, setLiveCounts] = useState<LiveCounts | null>(null);
  const [globalStats, setGlobalStats] = useState<DiscoverGlobalStats | null>(null);
  const [locationOptions, setLocationOptions] = useState<LocationOption[]>([]);
  const [syncedAssistantTotal, setSyncedAssistantTotal] = useState(0);
  const [scrapeStuck, setScrapeStuck] = useState(false);
  const lastScrapeProgress = useRef({ message: "", at: Date.now() });
  const [rescoring, setRescoring] = useState(false);
  const [rankingFit, setRankingFit] = useState(false);
  const [fitByJobId, setFitByJobId] = useState<
    Record<string, { verdict: string; overallScore: number; legitimacy?: string }>
  >({});
  const [atsFilter, setAtsFilter] = useState<AtsSource | "all">("all");
  const [seniorityFilter, setSeniorityFilter] = useState<Seniority | "all">("all");
  const [maxAgeDays, setMaxAgeDays] = useState<number | "all">("all");
  const [shortlist, setShortlist] = useState<Set<string>>(() => new Set());
  const [scoringShortlist, setScoringShortlist] = useState(false);
  const [queuedStarts, setQueuedStarts] = useState<Record<string, string>>({});
  const { status: prepQueue, refresh: refreshPrepQueue } = usePrepQueueStatus();

  useEffect(() => {
    if (!prepQueue) return;
    const active = new Set(prepQueue.queuedApplicationIds);
    setQueuedStarts((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const [scraperJobId, appId] of Object.entries(prev)) {
        if (!active.has(appId)) {
          delete next[scraperJobId];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [prepQueue]);
  const [addingToAssistant, setAddingToAssistant] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState("");
  const [error, setError] = useState("");
  const [gapPanelJob, setGapPanelJob] = useState<JobGapPanelJob | null>(null);
  const [gapAnalysis, setGapAnalysis] = useState<JobGapAnalysis | null>(null);
  const [gapLoading, setGapLoading] = useState(false);
  const [gapError, setGapError] = useState("");
  const [tier1Rescoring, setTier1Rescoring] = useState(false);
  const [qwenRescoring, setQwenRescoring] = useState(false);
  const [lastDismissed, setLastDismissed] = useState<DiscoverJob | null>(null);
  const [selectedJobIds, setSelectedJobIds] = useState<Set<string>>(new Set());
  const [batchImporting, setBatchImporting] = useState(false);
  const [batchProgress, setBatchProgress] = useState("");
  const postRescoringRef = useRef(false);

  function toggleSelectJob(jobId: string) {
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) {
        next.delete(jobId);
      } else {
        next.add(jobId);
      }
      return next;
    });
  }

  function toggleSelectAllVisible(visibleJobs: DiscoverJob[]) {
    const visibleIds = visibleJobs.map((j) => j.id);
    const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedJobIds.has(id));
    setSelectedJobIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        visibleIds.forEach((id) => next.delete(id));
      } else {
        visibleIds.forEach((id) => next.add(id));
      }
      return next;
    });
  }

  async function handleBatchLaunchPrep(visibleJobs: DiscoverJob[]) {
    const jobsToImport = visibleJobs.filter((j) => selectedJobIds.has(j.id));
    if (!jobsToImport.length) return;

    setBatchImporting(true);
    setBatchProgress(`Launching AI Prep for 0/${jobsToImport.length} jobs…`);
    let importedCount = 0;
    let failedCount = 0;

    const CHUNK_SIZE = 5;
    for (let i = 0; i < jobsToImport.length; i += CHUNK_SIZE) {
      const chunk = jobsToImport.slice(i, i + CHUNK_SIZE);
      await Promise.all(
        chunk.map(async (job) => {
          try {
            const result = await importScraperJob(job.id);
            const aaJobId = String((result.job as { id?: string })?.id || "");
            if (!result.prepStarted && aaJobId) {
              await qwenPrepareJob(aaJobId).catch(() => {});
            }
            removeJobFromList(job.id);
            importedCount++;
          } catch {
            failedCount++;
          }
        })
      );
      setBatchProgress(`Launching AI Prep for ${Math.min(i + CHUNK_SIZE, jobsToImport.length)}/${jobsToImport.length} jobs…`);
    }

    setSelectedJobIds(new Set());
    setBatchImporting(false);
    setBatchProgress("");
    invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
    await loadJobs();
    void loadAssistantSyncStatus();
    void refreshPrepQueue();
    setActionMsg(
      `Successfully launched AI Prep for ${importedCount} jobs!${failedCount > 0 ? ` (${failedCount} failed)` : ""}`
    );
  }

  const titleComboboxOptions = useMemo(
    () => filterOptions.titles.map((t) => ({ value: t, label: t })),
    [filterOptions.titles]
  );

  const locationComboboxOptions = useMemo(() => {
    const customList = locationOptions.map((opt) => ({
      value: opt.value,
      label: opt.label,
      sublabel: `${opt.count.toLocaleString()} roles`,
    }));
    const existing = new Set(customList.map((c) => c.value.toLowerCase()));
    LOCATION_QUICK_PICKS.forEach((pick) => {
      if (!existing.has(pick.toLowerCase())) {
        customList.push({ value: pick, label: pick, sublabel: "Quick pick" });
      }
    });
    return customList;
  }, [locationOptions]);

  const companyComboboxOptions = useMemo(
    () => TOP_50_COMPANIES.map((c) => ({ value: c, label: c })),
    []
  );
  const skipInitialFetch = useRef(false);
  const initializedFromWorkspace = useRef(false);
  const scrapingRef = useRef(false);
  const rescoringRef = useRef(false);

  useEffect(() => {
    scrapingRef.current = scraping;
  }, [scraping]);

  useEffect(() => {
    rescoringRef.current = rescoring;
  }, [rescoring]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok || cancelled) return;
        const status = (await res.json()) as StatusResponse;
        if (status.running) {
          setScraping(true);
          setScrapeMsg(status.progress || status.lastResult || "Running…");
          const next = liveCountsFromStatus(status);
          if (next) setLiveCounts(next);
        } else if (status.lastResult && status.progress === "Complete") {
          setScrapeMsg(status.lastResult);
          const next = liveCountsFromStatus(status);
          if (next) setLiveCounts(next);
        }
        if (status.tier1Rescore?.running) {
          setTier1Rescoring(true);
        }
        if (status.postRescore?.running) {
          postRescoringRef.current = true;
          setQwenRescoring(true);
        } else if (status.qwenRescore?.running) {
          setQwenRescoring(true);
        }
      } catch {
        /* status unavailable on mount */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (initializedFromWorkspace.current) return;
    initializedFromWorkspace.current = true;
    const nextQ = searchParams.get("q") || prefs.searchQuery || "";
    const nextLocation = searchParams.get("location") || prefs.location || "";
    const nextRole = searchParams.get("role") || prefs.roleFilter || "";
    const nextFreshness = searchParams.get("freshness") || prefs.freshness || "all";
    if (nextQ) setQ(nextQ);
    if (nextLocation) {
      setLocation(nextLocation);
      const parsed = nextLocation.split(",").map((s) => s.trim()).filter(Boolean);
      setSelectedLocations(parsed);
    }
    if (nextRole) setRole(nextRole);
    if (nextFreshness === "12" || nextFreshness === "24" || nextFreshness === "48" || nextFreshness === "72" || nextFreshness === "168" || nextFreshness === "336" || nextFreshness === "720" || nextFreshness === "all") {
      setFreshness(nextFreshness as FreshnessFilter);
    }
  }, [searchParams, prefs.searchQuery, prefs.location, prefs.roleFilter, prefs.freshness]);

  const syncFilterUrl = useCallback(
    (overrides?: Partial<{ q: string; company: string; location: string; role: string; freshness: FreshnessFilter }>) => {
      const params = new URLSearchParams();
      const values = {
        q: overrides?.q ?? q,
        location: overrides?.location ?? location,
        role: overrides?.role ?? role,
        freshness: overrides?.freshness ?? freshness,
      };
      if (values.q.trim()) params.set("q", values.q.trim());
      if (values.location.trim()) params.set("location", values.location.trim());
      if (values.role.trim()) params.set("role", values.role.trim());
      if (values.freshness !== "all") params.set("freshness", values.freshness);
      const qs = params.toString();
      const target = qs ? `/jobs/discover?${qs}` : "/jobs/discover";
      if(window.location.pathname + window.location.search !== target) router.replace(target, { scroll: false });
    },
    [q, location, role, freshness, router],
  );

  useEffect(() => {
    syncFilterUrl();
  }, [location, q, role, freshness, syncFilterUrl]);

  const loadGlobalStats = useCallback(async () => {
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/stats`, { cache: "no-store" });
      if (!res.ok) return;
      const payload = (await res.json()) as DiscoverGlobalStats & { success?: boolean };
      setGlobalStats({
        totalJobs: payload.totalJobs ?? 0,
        indexedCompanies: payload.indexedCompanies ?? 0,
        strongMatch: payload.strongMatch ?? 0,
        moderateMatch: payload.moderateMatch ?? 0,
        fresh48h: payload.fresh48h ?? 0,
        scrapedAt: payload.scrapedAt,
      });
    } catch {
      /* stats optional */
    }
  }, []);

  const loadLocationOptions = useCallback(async () => {
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/locations`, { cache: "no-store" });
      if (!res.ok) return;
      const payload = (await res.json()) as { success?: boolean; locations?: LocationOption[] };
      setLocationOptions(payload.locations ?? []);
    } catch {
      /* locations optional */
    }
  }, []);

  const loadAssistantSyncStatus = useCallback(async () => {
    try {
      const res = await getScraperSyncStatus();
      setSyncedAssistantTotal(res.syncedTotal ?? 0);
    } catch {
      /* assistant count optional */
    }
  }, []);

  useEffect(() => {
    void loadGlobalStats();
    void loadLocationOptions();
    void loadAssistantSyncStatus();
  }, [loadGlobalStats, loadLocationOptions, loadAssistantSyncStatus]);

  useEffect(() => {
    const cached = readDiscoverCache();
    if (!cached?.jobs.length) return;
    setData({
      success: true,
      jobs: cached.jobs as DiscoverJob[],
      total: cached.total,
      page: 1,
      totalPages: Math.max(1, Math.ceil(cached.total / 30)),
      scrapedAt: cached.scrapedAt,
      indexedCompanies: cached.indexedCompanies,
    });
    setLoading(false);
    if (isDiscoverCacheFresh()) {
      skipInitialFetch.current = true;
    }
  }, []);

  const requestVersion = useRef(0);
  const loadJobs = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      q,
      company,
      location,
      role: "",
      specialties:facets.specialties.join(","),
      seniorities:facets.seniorities.join(","),
      work_modes:facets.workModes.join(","),
      experience:facets.experience,
      companies:JSON.stringify(facets.companies),
      freshness,
      sponsorship,
      sort,
      page: String(page),
    });
    const url = `${getClientApiBaseUrl()}/jobs/discover?${params.toString()}`;

    try {
      const payload = await fetchCachedJson<DiscoverResponse>(url, {
        staleMs: scrapingRef.current ? 0 : undefined,
        timeoutMs: scrapingRef.current || rescoringRef.current ? 60_000 : undefined,
      });
      if(version !== requestVersion.current) return;
      setData(payload);
      if (payload.status?.running) {
        setScraping(true);
        setScrapeMsg(payload.status.progress || payload.status.lastResult || "Running…");
      }
      if (payload.jobs.length || payload.total) {
        writeDiscoverCache({
          jobs: payload.jobs,
          total: payload.total,
          scrapedAt: payload.scrapedAt,
          indexedCompanies: payload.indexedCompanies,
        });
      }
    } catch {
      if(version !== requestVersion.current) return;
      const cached = readDiscoverCache();
      if (cached?.jobs.length) {
        setData({
          success: true,
          jobs: cached.jobs as DiscoverJob[],
          total: cached.total,
          page: 1,
          totalPages: Math.max(1, Math.ceil(cached.total / 30)),
          scrapedAt: cached.scrapedAt,
          indexedCompanies: cached.indexedCompanies,
          status: { running: false, progress: "", lastResult: "Showing locally cached results" },
        });
        setError("API unavailable — showing last saved results from this browser.");
      } else {
        setError("Backend offline or job discover unavailable. Start the API and refresh.");
        setData(null);
      }
    } finally {
      if(version === requestVersion.current) setLoading(false);
    }
  }, [q, company, location, role, freshness, sponsorship, sort, page, facets]);

  useEffect(() => {
    if (skipInitialFetch.current) {
      skipInitialFetch.current = false;
      return;
    }
    const timer = setTimeout(()=>void loadJobs(),250);
    return () => {clearTimeout(timer);requestVersion.current++;};
  }, [loadJobs]);

  useEffect(() => {
    if (!scraping) return;

    const pollStatus = async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok) return;
        const status = (await res.json()) as StatusResponse;
        const progress = status.progress || status.lastResult || "Running…";
        const next = liveCountsFromStatus(status);
        if (next) setLiveCounts(next);
        const formatted = formatScrapeProgress(progress, next?.indexed);
        if (formatted !== lastScrapeProgress.current.message) {
          lastScrapeProgress.current = { message: formatted, at: Date.now() };
          setScrapeStuck(false);
        } else if (Date.now() - lastScrapeProgress.current.at > 3 * 60 * 1000) {
          setScrapeStuck(true);
        }
        setScrapeMsg(formatted);
        if (!status.running) {
          setScraping(false);
          setScrapeStuck(false);
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          void loadJobs();
          void loadGlobalStats();
          void loadLocationOptions();
          void loadAssistantSyncStatus();
          void refreshWorkspace();
          return;
        }
        invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
        void loadJobs();
      } catch {
        /* ignore polling errors */
      }
    };

    void pollStatus();
    const id = window.setInterval(() => void pollStatus(), 1500);
    return () => window.clearInterval(id);
  }, [scraping, loadJobs, loadGlobalStats, loadLocationOptions, loadAssistantSyncStatus, refreshWorkspace]);

  useEffect(() => {
    if (!tier1Rescoring) return;

    const pollTier1 = async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok) return;
        const status = (await res.json()) as StatusResponse;
        const tier1 = status.tier1Rescore;
        if (!tier1?.running) {
          setTier1Rescoring(false);
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          await loadJobs();
          if (tier1?.lastResult) {
            setActionMsg(tier1.lastResult);
          }
        } else if (tier1.progress) {
          setActionMsg(`Updating match scores: ${tier1.progress}`);
        }
      } catch {
        /* ignore */
      }
    };

    void pollTier1();
    const id = window.setInterval(() => void pollTier1(), 2500);
    return () => window.clearInterval(id);
  }, [tier1Rescoring, loadJobs]);

  useEffect(() => {
    if (!qwenRescoring) return;

    const pollPostRescore = async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/status`, { cache: "no-store" });
        if (!res.ok) return;
        const status = (await res.json()) as StatusResponse;
        const post = status.postRescore;
        const qwen = post?.qwenRescore ?? status.qwenRescore;
        const running = Boolean(post?.running || qwen?.running);
        if (!running) {
          postRescoringRef.current = false;
          setQwenRescoring(false);
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          await loadJobs();
          const note = post?.lastResult || qwen?.lastResult;
          if (note) {
            setActionMsg((prev) => (prev ? `${prev} ${note}` : note));
          }
          return;
        }
        const progress =
          post?.phase === "qwen"
            ? qwen?.progress || post.progress
            : post?.progress;
        if (progress) {
          setActionMsg((prev) => {
            const base = prev.replace(/\sAnalysis:.*$/, "");
            return base ? `${base} Analysis: ${progress}` : `Analysis: ${progress}`;
          });
        }
        if (post?.phase === "gap" && post.processed > 0) {
          invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
          void loadJobs();
        }
      } catch {
        /* ignore polling errors */
      }
    };

    void pollPostRescore();
    const id = window.setInterval(() => void pollPostRescore(), 2000);
    return () => window.clearInterval(id);
  }, [qwenRescoring, loadJobs]);

  const stats = useMemo(() => {
    if (scraping && liveCounts) {
      return {
        strong: liveCounts.strong,
        moderate: liveCounts.moderate,
        fresh: liveCounts.fresh,
      };
    }
    if (globalStats) {
      return {
        strong: globalStats.strongMatch,
        moderate: globalStats.moderateMatch,
        fresh: globalStats.fresh48h,
      };
    }
    const jobs = data?.jobs ?? [];
    return {
      strong: jobs.filter((job) => (job.relevancyScore ?? 0) >= 75).length,
      moderate: jobs.filter((job) => (job.relevancyScore ?? 0) >= 50 && (job.relevancyScore ?? 0) < 75).length,
      fresh: jobs.filter((job) => (job.freshness?.hours_ago ?? 999) <= 48).length,
    };
  }, [scraping, liveCounts, globalStats, data?.jobs]);

  const globalIndexed = globalStats?.totalJobs ?? data?.indexedTotal ?? liveCounts?.indexed ?? 0;
  const filteredTotal = data?.total ?? 0;
  const assistantTotal = Math.max(data?.assistantTotal ?? 0, syncedAssistantTotal);
  const perPage = data?.perPage ?? 30;
  const filtersActive = Boolean(q || company || location || role || freshness !== "all" || sponsorship !== "all");
  const triageFiltersActive = atsFilter !== "all" || seniorityFilter !== "all" || maxAgeDays !== "all";
  const anyFiltersActive = filtersActive || triageFiltersActive || sort !== "relevancy";
  const filterHidingResults = !scraping && filteredTotal === 0 && filtersActive;
  const filterVeryNarrow =
    !scraping && !loading && filtersActive && globalIndexed > 100 && filteredTotal > 0 && filteredTotal <= 30;
  const allInAssistant = !loading && !scraping && filteredTotal === 0 && assistantTotal > 0 && !filtersActive;
  const headerIndexed = scraping && liveCounts ? liveCounts.indexed : globalIndexed;
  const headerCompanies = scraping && liveCounts ? liveCounts.companies : globalStats?.indexedCompanies ?? data?.indexedCompanies ?? 0;

  function removeJobFromList(jobId: string, queued = false) {
    setData((prev) => {
      if (!prev) return prev;
      const perPage = prev.perPage ?? 30;
      const nextTotal = Math.max(0, prev.total - 1);
      return {
        ...prev,
        jobs: prev.jobs.filter((job) => job.id !== jobId),
        total: nextTotal,
        totalPages: Math.max(1, Math.ceil(nextTotal / perPage) || 1),
        assistantTotal: (prev.assistantTotal ?? syncedAssistantTotal) + (queued ? 1 : 0),
      };
    });
    if(queued) setSyncedAssistantTotal((prev) => prev + 1);
  }

  async function handleCancelScrape() {
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/scrape/cancel`, { method: "POST" });
      if (!res.ok) throw new Error("Could not cancel scrape");
      setScraping(false);
      setScrapeStuck(false);
      setScrapeMsg("Scrape cancelled — partial results kept.");
      invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
      await loadJobs();
      await loadGlobalStats();
      await loadLocationOptions();
      await refreshWorkspace();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel scrape.");
    }
  }

  async function handleScrape(hours: number, mode: ScrapeMode = "ats") {
    const cappedHours = Math.min(Math.max(hours, 1), 720);
    const targetFreshness = String(cappedHours) as FreshnessFilter;
    const locStr = selectedLocations.join(", ");
    if (locStr !== location) {
      setLocation(locStr);
    }
    if (["12", "24", "48", "72", "168", "336", "720"].includes(targetFreshness)) {
      setFreshness(targetFreshness);
      setPage(1);
      updatePrefs({ freshness: targetFreshness, location: locStr });
    }
    setScraping(true);
    setScrapeStuck(false);
    setScrapeMsg("Starting…");
    lastScrapeProgress.current = { message: "Starting…", at: Date.now() };
    setError("");
    invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/scrape`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hours: cappedHours, roles: "", mode }),
      });
      const body = (await res.json().catch(() => ({}))) as { success?: boolean; error?: string; detail?: string };
      if (!res.ok || body.success === false) {
        const detail =
          body.error ||
          (typeof body.detail === "string" ? body.detail : "") ||
          (res.status === 409 ? "A scrape is already running — click Cancel scrape or wait." : "Scrape failed to start");
        throw new Error(detail);
      }
      setScrapeMsg("Scrape started — fetching roles…");
    } catch (err) {
      setScraping(false);
      setScrapeMsg("");
      const message = err instanceof Error ? err.message : "Scrape failed to start";
      setError(message.includes("API") ? message : `Could not start scrape. ${message}`);
    }
  }

  // Two actions, matching what the product actually does with a job:
  //
  //   Apply        - import it into the Autopilot queue and submit, the same
  //                  path the Applications view's Apply uses.
  //   Add to queue - import only. Deliberately independent of the Qwen prep
  //                  step, so it keeps working while preprocessing is off;
  //                  the old "AI Prep" button bundled the two together, which
  //                  made plain queueing unreachable whenever prep was
  //                  disabled or its queue was full.
  //
  // The previous "Apply" was an <a> to the employer's site, which opened the
  // posting in a new tab and left CareerOS with no record of it at all.
  async function queueJob(job: DiscoverJob): Promise<string> {
    const result = await importScraperJob(job.id);
    const aaJobId = String((result.job as { id?: string })?.id || "");
    removeJobFromList(job.id, true);
    invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
    void loadJobs();
    void loadAssistantSyncStatus();
    window.dispatchEvent(new CustomEvent("careeros-job-counts-changed"));
    return aaJobId;
  }

  async function handleAddToQueue(job: DiscoverJob) {
    setActionMsg("");
    setError("");
    if (addingToAssistant === job.id) return;
    setAddingToAssistant(job.id);
    try {
      await queueJob(job);
      setActionMsg(`Added ${job.companyName} to the Autopilot queue.`);
    } catch (err) {
      setActionMsg(err instanceof Error ? err.message : "Could not add this job to the queue.");
    } finally {
      setAddingToAssistant(null);
    }
  }

  async function handleApplyNow(job: DiscoverJob) {
    setActionMsg("");
    setError("");
    if (addingToAssistant === job.id) return;
    setAddingToAssistant(job.id);
    try {
      const aaJobId = await queueJob(job);
      if (!aaJobId) {
        setActionMsg(`Added ${job.companyName} to the queue, but could not start the application.`);
        return;
      }
      await approvePreflightSubmission(aaJobId);
      setActionMsg(`Applying to ${job.companyName} — follow it on the Autopilot page.`);
    } catch (err) {
      setActionMsg(err instanceof Error ? err.message : "Could not start this application.");
    } finally {
      setAddingToAssistant(null);
    }
  }

  async function handleAddToAssistant(job: DiscoverJob) {
    setActionMsg("");
    setError("");

    if (prepQueue && prepQueue.available <= 0) {
      setActionMsg(`Prep queue full (${prepQueue.queued}/${prepQueue.maxQueue}). Wait for running jobs to finish.`);
      return;
    }

    if (addingToAssistant === job.id || queuedStarts[job.id]) {
      if (queuedStarts[job.id]) {
        setActionMsg(`${job.companyName} is already in the prep queue.`);
      }
      return;
    }

    setAddingToAssistant(job.id);
    try {
      const result = await importScraperJob(job.id);
      const aaJobId = String((result.job as { id?: string })?.id || "");
      let applicationId = result.applicationId;

      if (!result.prepStarted && aaJobId) {
        try {
          const retry = await qwenPrepareJob(aaJobId);
          if (retry.applicationId) applicationId = retry.applicationId;
        } catch {
          /* queue may be full — application still appears in pipeline */
        }
      }

      removeJobFromList(job.id);
      invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
      await loadJobs();
      void loadLocationOptions();
      void loadAssistantSyncStatus();
      if (applicationId) {
        setQueuedStarts((prev) => ({ ...prev, [job.id]: applicationId! }));
      }
      window.dispatchEvent(new CustomEvent("qwen-prep-started"));
      window.dispatchEvent(new CustomEvent("careeros-job-counts-changed"));
      void refreshPrepQueue();

      const destination = applicationId
        ? `/application-assistant?app=${encodeURIComponent(applicationId)}`
        : "/application-assistant#application-queue";
      router.push(destination);

      const queue = result.queue;
      if (result.prepStarted) {
        setActionMsg(
          queue
            ? `Added ${job.companyName} — prep queued (${queue.running} running, ${queue.waiting} waiting).`
            : `Added ${job.companyName} — opening AI Assistant queue.`,
        );
      } else if (result.prepError) {
        setActionMsg(`Added ${job.companyName} to the queue. Prep waiting: ${result.prepError}`);
      } else {
        setActionMsg(`Added ${job.companyName} — opening AI Assistant queue.`);
      }
    } catch (err) {
      setActionMsg(err instanceof Error ? err.message : "Could not add job to AI Assistant.");
    } finally {
      setAddingToAssistant(null);
    }
  }

  async function handleDismissJob(job: DiscoverJob) {
    removeJobFromList(job.id);
    setLastDismissed(job);
    invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
    try {
      const response = await fetch(`${getClientApiBaseUrl()}/jobs/discover/${job.id}/dismiss`, { method: "POST" });
      if(!response.ok) throw new Error();
    } catch {
      setLastDismissed(null);
      await loadJobs();
      setError("Could not hide this posting. Please try again.");
    }
  }

  async function handleUndismissJob(job: DiscoverJob) {
    setLastDismissed(null);
    try {
      await fetch(`${getClientApiBaseUrl()}/jobs/discover/${job.id}/undismiss`, { method: "POST" });
    } catch {
      /* fallback */
    }
    invalidateCachedByPrefix(`${getClientApiBaseUrl()}/jobs/discover?`);
    await loadJobs();
  }

  const visibleJobs = useMemo(() => {
    const jobs = data?.jobs ?? [];
    return jobs.filter((job) =>
      matchesTriageFilters(
        { id: job.id, title: job.title, url: job.url, updatedAt: job.updatedAt },
        { ats: atsFilter, seniority: seniorityFilter, maxAgeDays },
      ),
    );
  }, [data?.jobs, atsFilter, seniorityFilter, maxAgeDays]);

  useEffect(() => {
    const visibleIds = new Set(visibleJobs.map(job=>job.id));
    setSelectedJobIds(previous => {
      const next = new Set([...previous].filter(id=>visibleIds.has(id)));
      return next.size === previous.size ? previous : next;
    });
  }, [visibleJobs]);

  const triageHidingRows =
    !loading && (data?.jobs?.length ?? 0) > 0 && visibleJobs.length < (data?.jobs?.length ?? 0);

  function toggleShortlist(jobId: string) {
    setShortlist((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  async function handleScoreShortlist() {
    if (shortlist.size === 0) return;
    setScoringShortlist(true);
    setError("");
    try {
      const jobsToScore = (data?.jobs ?? []).filter((job) => shortlist.has(job.id));
      const next: Record<string, { verdict: string; overallScore: number; legitimacy?: string }> = { ...fitByJobId };
      for (const job of jobsToScore) {
        const res = await fetch(`${getClientApiBaseUrl()}/jobs/evaluate-fit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job: {
              id: job.id,
              title: job.title,
              companyName: job.companyName,
              location: job.location,
              url: job.url,
              description: job.description || job.keywordsMatched?.join(" ") || "",
            },
          }),
        });
        if (!res.ok) continue;
        const body = (await res.json()) as {
          evaluation?: { verdict?: string; overallScore?: number; legitimacy?: { verdict?: string } };
        };
        const evaluation = body.evaluation;
        if (evaluation?.verdict != null && evaluation.overallScore != null) {
          next[job.id] = {
            verdict: evaluation.verdict,
            overallScore: evaluation.overallScore,
            legitimacy: evaluation.legitimacy?.verdict,
          };
        }
      }
      setFitByJobId(next);
      setActionMsg(`Scored ${jobsToScore.length} shortlisted role${jobsToScore.length === 1 ? "" : "s"}.`);
    } catch {
      setError("Could not score shortlist.");
    } finally {
      setScoringShortlist(false);
    }
  }

  async function handleRankByFit() {
    setRankingFit(true);
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/rank`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: 100 }),
      });
      if (!res.ok) throw new Error("Fit rank failed");
      const body = (await res.json()) as {
        shortlistCount?: number;
        jobs?: Array<{
          id: string;
          rankVerdict?: string;
          rankScore?: number;
          fitEvaluation?: { legitimacy?: { verdict?: string } };
        }>;
      };
      const next: Record<string, { verdict: string; overallScore: number; legitimacy?: string }> = {};
      for (const job of body.jobs ?? []) {
        if (job.id && job.rankVerdict != null && job.rankScore != null) {
          next[job.id] = {
            verdict: job.rankVerdict,
            overallScore: job.rankScore,
            legitimacy: job.fitEvaluation?.legitimacy?.verdict,
          };
        }
      }
      setFitByJobId(next);
      setActionMsg(
        `Ranked ${body.shortlistCount ?? 0} jobs by multi-dimension fit (technical, experience, behavioral, career).`,
      );
    } catch {
      setError("Fit ranking failed. Confirm the API is running.");
    } finally {
      setRankingFit(false);
    }
  }

  async function handleRescore() {
    setRescoring(true);
    setError("");
    setActionMsg("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/rescore?force=true`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Could not refresh match scores");
      const body = (await res.json()) as { started?: boolean; error?: string };
      if (!body.started) {
        setActionMsg(body.error || "Match scores are already up to date.");
        return;
      }
      setTier1Rescoring(true);
      setActionMsg("Updating match scores for all indexed jobs in the background…");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not refresh match scores");
    } finally {
      setRescoring(false);
    }
  }

  async function openGapPanel(job: DiscoverJob) {
    const panelJob: JobGapPanelJob = {
      id: job.id,
      title: job.title,
      companyName: job.companyName,
      location: job.location,
      url: job.url,
      relevancyScore: job.relevancyScore,
    };
    setGapPanelJob(panelJob);
    setGapError("");
    if (job.gapAnalysis) {
      setGapAnalysis(job.gapAnalysis);
      setGapLoading(false);
      return;
    }
    setGapAnalysis(null);
    setGapLoading(true);
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/jobs/discover/gap-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jobId: job.id }),
      });
      const body = (await res.json()) as { analysis?: JobGapAnalysis; detail?: string; qwenStarted?: boolean };
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Could not analyze match gap");
      }
      if (!body.analysis) {
        throw new Error("No analysis returned");
      }
      setGapAnalysis(body.analysis);
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          jobs: prev.jobs.map((row) => (row.id === job.id ? { ...row, gapAnalysis: body.analysis } : row)),
        };
      });
      if (body.qwenStarted) {
        postRescoringRef.current = true;
        setQwenRescoring(true);
      }
    } catch (err) {
      setGapError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setGapLoading(false);
    }
  }

  function closeGapPanel() {
    setGapPanelJob(null);
    setGapAnalysis(null);
    setGapError("");
  }

  function clearFilters() {
    setFacets({specialties:[],seniorities:[],workModes:[],experience:"",companies:[]});
    setQ("");
    setCompany("");
    setLocation("");
    setSelectedLocations([]);
    setRole("");
    setFreshness("all");
    setSponsorship("all");
    setSort("relevancy");
    setAtsFilter("all");
    setSeniorityFilter("all");
    setMaxAgeDays("all");
    setPage(1);
    updatePrefs({
      searchQuery: "",
      location: "",
      roleFilter: "",
      freshness: "all",
    });
    router.replace("/jobs/discover", { scroll: false });
  }

  const fetchHours = useMemo(() => {
    if (freshness === "all") return 720;
    const parsed = parseInt(freshness, 10);
    return Number.isNaN(parsed) ? 168 : parsed;
  }, [freshness]);

  const fetchLabel = useMemo(() => {
    if (scraping) return "Scraping…";
    switch (freshness) {
      case "12": return "Fetch 12h";
      case "24": return "Fetch 24h";
      case "48": return "Fetch 48h";
      case "72": return "Fetch 3 days";
      case "168": return "Fetch 7 days";
      case "336": return "Fetch 14 days";
      case "720": return "Fetch 30 days";
      default: return "Fetch roles";
    }
  }, [scraping, freshness]);

  // Job Discovery is meant to pull broadly — filtering down to what you actually
  // want to apply to happens on the Autopilot "Ready to Apply" board instead.
  // Title/location are optional refinements here, not gates on fetching at all.
  const isFormValid = true;

  function applyLocationFilter(pick: string) {
    let nextLocs: string[];
    if (!pick) {
      nextLocs = [];
    } else {
      const exists = selectedLocations.some((l) => l.toLowerCase() === pick.toLowerCase());
      if (exists) {
        nextLocs = selectedLocations.filter((l) => l.toLowerCase() !== pick.toLowerCase());
      } else {
        nextLocs = [...selectedLocations, pick];
      }
    }
    setSelectedLocations(nextLocs);
    const locStr = nextLocs.join(", ");
    setLocation(locStr);
    setPage(1);
    updatePrefs({ location: locStr });
  }

  function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isFormValid || scraping) return;
    const form = new FormData(event.currentTarget);
    const nextQ = String(form.get("q") || "").trim();
    const nextCompany = String(form.get("company") || "").trim();
    const locStr = selectedLocations.join(", ");
    const nextRole = String(form.get("role") || "").trim();
    setQ(nextQ);
    setCompany(nextCompany);
    setLocation(locStr);
    setRole(nextRole);
    setPage(1);
    updatePrefs({
      searchQuery: nextQ,
      location: locStr,
      roleFilter: nextRole,
      freshness,
    });
    void loadJobs();
  }

  return (
    <div className={`${styles.browse} target-jobs-dashboard job-discover-dashboard${scraping ? " job-discover-dashboard--scraping" : ""}`}>
      <header className={styles.pageHeader}><div><span>YOUR NEXT OPPORTUNITY</span><h1>Browse jobs</h1><p>Find your fit. Build a shortlist. Move forward with intention.</p></div><a href="/applications?tab=queued">Open Autopilot queue ↗</a></header>
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">OPPORTUNITY LIBRARY</span>
            <h2 className={scraping ? "job-discover-live-count" : undefined}>
              {scraping
                ? `${headerIndexed.toLocaleString()} indexed roles`
                : `${filteredTotal.toLocaleString()} roles to review`}
              {!scraping && filtersActive && filteredTotal !== globalIndexed ? (
                <span className="muted" style={{ fontSize: "0.95rem", fontWeight: 500 }}>
                  {" "}
                  · {filteredTotal.toLocaleString()} match filters
                </span>
              ) : null}
            </h2>
            <p className="muted" style={{ marginTop: "0.35rem" }}>
              Last scraped: {formatRefreshed(globalStats?.scrapedAt ?? data?.scrapedAt)} · {headerCompanies} companies · max 30 days
              {!scraping && assistantTotal > 0 ? ` · ${assistantTotal.toLocaleString()} in AI Assistant` : ""}
              {!scraping && globalIndexed > 0 ? ` · ${globalIndexed.toLocaleString()} indexed total` : ""}
              {scraping && filteredTotal > 0 ? ` · ${filteredTotal.toLocaleString()} match filters` : ""}
              {snapshot?.profile?.targetRole ? ` · scoring for ${snapshot.profile.targetRole}` : ""}
              {scraping ? ` · ${scrapeMsg || "Running…"}` : scrapeMsg ? ` · ${scrapeMsg}` : ""}
            </p>
          </div>
          <details className={styles.tools}><summary>Library tools</summary><div className="target-jobs-actions">
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleRescore()} disabled={rescoring || tier1Rescoring}>
              {rescoring || tier1Rescoring ? "Updating scores…" : "Refresh all scores"}
            </button>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleRankByFit()} disabled={rankingFit}>
              {rankingFit ? "Ranking fit…" : "Rank by fit"}
            </button>
            {scraping ? (
              <button type="button" className="btn btn-sm btn-secondary" onClick={() => void handleCancelScrape()}>
                Cancel scrape
              </button>
            ) : null}
          </div></details>
        </div>

        <BrowseFilterControls value={{q,location,company,...facets,freshness,sponsorship,sort}} options={filterOptions}
          onChange={patch=>{
            if(patch.q!==undefined)setQ(patch.q);if(patch.company!==undefined)setCompany(patch.company);
            if(patch.location!==undefined){setLocation(patch.location);setSelectedLocations(patch.location.split(",").map(v=>v.trim()).filter(Boolean));}
            if(patch.freshness!==undefined)setFreshness(patch.freshness as FreshnessFilter);
            if(patch.sponsorship!==undefined)setSponsorship(patch.sponsorship as SponsorshipFilter);
            if(patch.sort!==undefined)setSort(patch.sort as SortFilter);
            setFacets(previous=>({specialties:patch.specialties??previous.specialties,seniorities:patch.seniorities??previous.seniorities,workModes:patch.workModes??previous.workModes,experience:patch.experience??previous.experience,companies:patch.companies??previous.companies}));setRole("");setPage(1);
          }} onClear={clearFilters} onFetch={()=>void handleScrape(fetchHours,"all")} scraping={scraping} total={filteredTotal}
          titleInput={<SearchableCombobox name="q" value={q} onChange={val=>{setQ(val);setRole("");setPage(1);}} options={titleComboboxOptions} placeholder="Search any role, including PM or BIE"/>}
          locationInput={<MultiSelectCombobox name="location" selectedValues={selectedLocations} onChange={vals=>{setSelectedLocations(vals);setLocation(vals.join(", "));setPage(1);}} options={locationComboboxOptions} placeholder="Add cities, regions or countries"/>}
        />

        <details className={styles.quickLocations}><summary>Quick location picks</summary><div className="job-discover-location-chips" aria-label="Quick location filters">
          <span className="job-discover-location-chips-label">Location:</span>
          <button
            type="button"
            className={`job-discover-location-chip${selectedLocations.length === 0 ? " job-discover-location-chip--active" : ""}`}
            onClick={() => applyLocationFilter("")}
          >
            All
          </button>
          {LOCATION_QUICK_PICKS.map((pick) => {
            const active = selectedLocations.some((l) => l.toLowerCase() === pick.toLowerCase());
            return (
              <button
                key={pick}
                type="button"
                className={`job-discover-location-chip${active ? " job-discover-location-chip--active" : ""}`}
                onClick={() => applyLocationFilter(pick)}
              >
                {pick}
              </button>
            );
          })}
        </div>

        </details><div className="target-jobs-stats">
          <article className="stat-card">
            <p className="stat-label">Strong match</p>
            <p className={`stat-value${scraping ? " job-discover-live-stat" : ""}`}>{stats.strong.toLocaleString()}</p>
          </article>
          <article className="stat-card">
            <p className="stat-label">Moderate</p>
            <p className={`stat-value${scraping ? " job-discover-live-stat" : ""}`}>{stats.moderate.toLocaleString()}</p>
          </article>
          <article className="stat-card">
            <p className="stat-label">Posted &lt;48h</p>
            <p className={`stat-value${scraping ? " job-discover-live-stat" : ""}`}>{stats.fresh.toLocaleString()}</p>
          </article>
          <article className="stat-card">
            <p className="stat-label">In Assistant</p>
            <p className="stat-value">
              <a href="/application-assistant" className="job-discover-assistant-stat-link">
                {assistantTotal.toLocaleString()}
              </a>
            </p>
          </article>
          <article className="stat-card">
            <p className="stat-label">Page</p>
            <p className="stat-value">{data?.page ?? 1}/{data?.totalPages ?? 1}</p>
          </article>
        </div>

        {filterHidingResults ? (
          <p className="email-sender-status email-sender-status--warn">
            No roles match your current filters
            {location ? ` (location: ${location})` : ""}
            {role ? ` (roles: ${role})` : ""}
            {freshness !== "all" ? ` (posted: ${postedAgoLabel(freshness).toLowerCase()})` : ""}
            .{" "}
            <button type="button" className="btn btn-sm btn-secondary" onClick={clearFilters} style={{ marginLeft: "0.35rem" }}>
              Clear filters
            </button>
          </p>
        ) : null}
        {filterVeryNarrow ? (
          <p className="email-sender-status email-sender-status--warn">
            Filters narrowed {globalIndexed.toLocaleString()} indexed roles down to {filteredTotal.toLocaleString()}
            {q ? ` · search: “${q}”` : ""}
            {location ? ` · location: ${location}` : ""}
            {role ? ` · roles: ${role}` : ""}
            {freshness !== "all" ? ` · posted: ${postedAgoLabel(freshness).toLowerCase()}` : ""}
            .{" "}
            <button type="button" className="btn btn-sm btn-secondary" onClick={clearFilters} style={{ marginLeft: "0.35rem" }}>
              Show all roles
            </button>
          </p>
        ) : null}
        {triageHidingRows ? (
          <p className="muted text-sm">
            Quick filters hid {(data?.jobs?.length ?? 0) - visibleJobs.length} of {data?.jobs?.length ?? 0} roles on this page.
            Reset ATS, level, or age chips above to see more.
          </p>
        ) : null}
        {allInAssistant ? (
          <p className="email-sender-status email-sender-status--ok">
            All scraped roles are in AI Assistant ({assistantTotal.toLocaleString()} total).{" "}
            <a href="/application-assistant">Open AI Assistant</a> to review and apply.
          </p>
        ) : null}
        {scraping ? (
          <div className="cos-scrape-progress-banner" role="status" aria-live="polite">
            <div className="cos-scrape-progress-header">
              <div className="cos-scrape-progress-info">
                <div className="cos-spinner-pulse" />
                <span>
                  <strong>Scrape in progress:</strong> {scrapeMsg || "Starting ATS & career board ingestion…"}
                  {liveCounts ? ` · ${liveCounts.indexed.toLocaleString()} roles saved` : ""}
                </span>
              </div>
              {scrapeStuck ? (
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  onClick={() => void handleCancelScrape()}
                >
                  Cancel & keep partial
                </button>
              ) : (
                <span className="muted text-sm">Ingesting background feeds…</span>
              )}
            </div>
            <div className="cos-progress-bar-track">
              <div className="cos-progress-bar-fill" />
            </div>
          </div>
        ) : null}
        {error ? <p className="email-sender-status email-sender-status--warn">{error}</p> : null}
        {!scraping && scrapeMsg ? <p className="muted">{scrapeMsg}</p> : null}
        {actionMsg ? <p className="muted">{actionMsg}</p> : null}
        {lastDismissed ? (
          <p className="email-sender-status email-sender-status--ok">
            Marked <strong>{lastDismissed.title}</strong> at {lastDismissed.companyName} as not relevant.{" "}
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => void handleUndismissJob(lastDismissed)}
              style={{ marginLeft: "0.35rem" }}
            >
              Undo
            </button>
          </p>
        ) : null}
        {prepQueue && (prepQueue.queued > 0 || (prepQueue.openBrowserCount ?? 0) > 0) ? (
          <p className="email-sender-status email-sender-status--ok" role="status">
            Prep queue: {prepQueue.running} running · {prepQueue.waiting} waiting · {prepQueue.available} slots left
            {" "}(max {prepQueue.maxConcurrent} parallel, {prepQueue.maxQueue} total)
            {(prepQueue.openBrowserCount ?? 0) > 0
              ? ` · ${prepQueue.openBrowserCount} browser window${prepQueue.openBrowserCount === 1 ? "" : "s"} open`
              : ""}
            {" · "}
            <a href="/application-assistant">Open AI Assistant</a>
          </p>
        ) : null}
      </section>

      <section id="browse-results" className="workflow-panel data-panel" aria-busy={loading}>
        <div className="data-panel-header">
          <div>
            <span className="toc-card-kicker">Matches</span>
            <h2>
              {loading
                ? "Loading…"
                : scraping
                  ? `${(data?.total ?? 0).toLocaleString()} to review · ${(liveCounts?.indexed ?? headerIndexed ?? 0).toLocaleString()} indexed`
                  : `${filteredTotal.toLocaleString()} roles to review`}
            </h2>
            {!loading && assistantTotal > 0 ? (
              <p className="muted job-discover-assistant-count">
                <a href="/application-assistant">{assistantTotal.toLocaleString()} in AI Assistant</a>
              </p>
            ) : null}
          </div>
        </div>

        {loading && !(data?.jobs.length) ? <WorkspaceLoading label="Finding your next opportunity…" /> : !visibleJobs.length ? (
          <p className="muted">
            {filterHidingResults
              ? "Widen or clear filters above to see roles to review."
              : allInAssistant
                ? "Nothing left to review — open AI Assistant to work through your queue."
                : globalIndexed > 0
                  ? "No roles on this page. Try the next page or adjust quick filters."
                  : "No jobs matched. Run a scrape or widen filters. Fill in your profile skills and title for relevancy scoring."}
          </p>
        ) : (
          <>
            {!loading && (data?.jobs?.length ?? 0) > 0 ? (
              <details className={styles.quickLocations}><summary>Refine this page · source, seniority & shortlist</summary><DiscoverTriageBar
                jobs={data?.jobs ?? []}
                atsFilter={atsFilter}
                seniorityFilter={seniorityFilter}
                maxAgeDays={maxAgeDays}
                shortlist={shortlist}
                onAtsFilter={setAtsFilter}
                onSeniorityFilter={setSeniorityFilter}
                onMaxAgeDays={setMaxAgeDays}
                onToggleShortlist={toggleShortlist}
                onClearShortlist={() => setShortlist(new Set())}
                onScoreShortlist={() => void handleScoreShortlist()}
                scoringShortlist={scoringShortlist}
              /></details>
            ) : null}

            {visibleJobs.length > 0 ? (
              <div
                className="cos-batch-selection-bar"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "0.65rem 1rem",
                  marginBlock: "0.5rem 0.75rem",
                  backgroundColor: selectedJobIds.size > 0 ? "rgba(98, 221, 197, 0.08)" : "#11161d",
                  border: `1px solid ${selectedJobIds.size > 0 ? "#62ddc5" : "rgba(166, 181, 201, 0.16)"}`,
                  borderRadius: "10px",
                  transition: "all 0.15s ease",
                }}
              >
                <label style={{ display: "flex", alignItems: "center", gap: "0.6rem", cursor: "pointer", fontSize: "0.875rem", fontWeight: 600, color: "#f5f8fb" }}>
                  <input
                    type="checkbox"
                    checked={visibleJobs.length > 0 && visibleJobs.every((j) => selectedJobIds.has(j.id))}
                    onChange={() => toggleSelectAllVisible(visibleJobs)}
                    style={{ width: "1.1rem", height: "1.1rem", cursor: "pointer", accentColor: "#62ddc5" }}
                  />
                  <span>
                    {selectedJobIds.size > 0
                      ? `${selectedJobIds.size} ${selectedJobIds.size === 1 ? "role" : "roles"} selected`
                      : `Select all ${visibleJobs.length} roles on page`}
                  </span>
                </label>
                {selectedJobIds.size > 0 ? (
                  <div style={{ display: "flex", alignItems: "center", gap: "0.65rem" }}>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      onClick={() => setSelectedJobIds(new Set())}
                      disabled={batchImporting}
                    >
                      Deselect all
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={() => void handleBatchLaunchPrep(visibleJobs)}
                      disabled={batchImporting}
                      style={{
                        background: "linear-gradient(135deg, #62ddc5 0%, #84cbe6 100%)",
                        color: "#07130f",
                        fontWeight: 700,
                        border: 0,
                        paddingInline: "1rem",
                      }}
                    >
                      {batchImporting ? batchProgress : `⚡ Launch AI Prep (${selectedJobIds.size})`}
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}

            {/* Quick Sort Bar */}
            <div
              className="job-discover-sort-bar"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: "0.5rem",
                marginBlock: "0.5rem 0.75rem",
                padding: "0.5rem 0.85rem",
                backgroundColor: "var(--bg-elevated, #11161d)",
                border: "1px solid var(--border, rgba(166, 181, 201, 0.16))",
                borderRadius: "10px",
              }}
            >
              <ChoiceGroup label="Sort results" options={[{value:"relevancy",label:"Best match"},{value:"date",label:"Newest"},{value:"company",label:"Company"}]} value={[sort]} onChange={([value])=>{setSort(value as SortFilter);setPage(1);}}/>
              <span className="muted text-sm">
                {visibleJobs.length} visible on this page · {filteredTotal.toLocaleString()} matching roles
              </span>
            </div>

            <div className={styles.grid} role="list">
              {visibleJobs.map(job => <DiscoverJobCard key={job.id} job={job}
                selected={selectedJobIds.has(job.id)} shortlisted={shortlist.has(job.id)}
                busy={loading || addingToAssistant !== null} queued={Boolean(queuedStarts[job.id])}
                fit={fitByJobId[job.id]} onSelect={()=>toggleSelectJob(job.id)}
                onShortlist={()=>toggleShortlist(job.id)} onHide={()=>void handleDismissJob(job)}
                onDetails={()=>void openGapPanel(job)} onQueue={()=>void handleAddToQueue(job)}
                onApply={()=>void handleApplyNow(job)}/>) }
            </div>
            </>
          )}

          {(data?.totalPages ?? 0) > 1 ? (
            <div
              className="job-discover-pagination"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "0.85rem",
                marginTop: "1.5rem",
                padding: "1rem",
              }}
            >
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                disabled={loading || page <= 1}
                onClick={() => { setPage((p) => Math.max(1, p - 1)); document.getElementById("browse-results")?.scrollIntoView({block:"start",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"}); }}
              >
                ← Previous
              </button>
              <span className="muted" style={{ fontWeight: 600 }}>
                Page {page} of {data?.totalPages ?? 1}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                disabled={loading || page >= (data?.totalPages ?? 1)}
                onClick={() => { setPage((p) => p + 1); document.getElementById("browse-results")?.scrollIntoView({block:"start",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"}); }}
              >
                Next →
              </button>
            </div>
          ) : null}
      </section>

      <JobMatchGapPanel
        open={Boolean(gapPanelJob)}
        loading={gapLoading}
        error={gapError}
        job={gapPanelJob}
        analysis={gapAnalysis}
        onClose={closeGapPanel}
      />
    </div>
  );
}
