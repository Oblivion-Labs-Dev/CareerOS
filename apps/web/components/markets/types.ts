export type H1BStrength = "strong" | "moderate" | "weak";
export type StatusBucket = "healthy" | "manual" | "degraded" | "failed" | "pending";
export type JobsState = "known" | "pending" | "unknown";

export interface MarketZone {
  id: string;
  label: string;
  treatment?: string;
}

export interface MarketInfo {
  id: string;
  name: string;
  tagline: string;
  origin: string;
  state: string;
  areas: { name: string; zone: string }[];
  zones: MarketZone[];
}

export interface CompanyH1B {
  strength: H1BStrength;
  label: string;
  score: number | null;
  activity: string | null;
  localLcaCount: number | null;
  lcaArea: string | null;
  evidence: string | null;
  evidenceUrls: string[];
  source: string | null;
  note: string;
}

export interface CompanyCareer {
  url: string;
  urlSource: string;
  seedUrl: string;
  rejectedUrl?: string | null;
  alternateUrls: { label: string; url: string; source: string }[];
  provider: string | null;
  label: string;
  sourceType: string;
  health: string;
  status: StatusBucket;
  method: string | null;
  confidence: number | null;
  evidence: string | null;
  detectedAt: string | null;
  lastAttemptAt: string | null;
  lastSuccessAt: string | null;
  failureReason: string;
  httpStatus: number | null;
  sourceChange?: { from: string; to: string; at: string } | null;
  seedParseability?: string | null;
  detectionSteps?: { step: string; outcome: string; [key: string]: unknown }[];
}

export interface CompanyJobs {
  state: JobsState;
  totalOpen: number | null;
  inMarket: number | null;
  scope: string | null;
  scopeLabel: string | null;
  truncated: boolean;
  stale: boolean;
  relevant: number;
  relevantOfficial: number;
  scanRelevant: number | null;
  highMatch: number;
  newCount: number;
  newSinceLastScan: number;
  otherSources: number;
  lastScanAt: string | null;
  lastSuccessAt: string | null;
}

export interface MarketCompany {
  id: string;
  name: string;
  displayName: string;
  kind: string;
  tier: number | null;
  tierLabel: string | null;
  priority: number | null;
  category: string | null;
  areas: string[];
  localPresence: string | null;
  zone: string | null;
  zoneLabel: string | null;
  fitScore: number | null;
  whyFits: string | null;
  notes: string | null;
  h1b: CompanyH1B;
  career: CompanyCareer;
  jobs: CompanyJobs;
  provenance: {
    source: string | null;
    seeds: Record<string, { row: number; file: string; importedAt: string }>;
    sourceImportedAt: string | null;
    firstImportedAt: string | null;
  };
}

export interface CompanyDetail extends MarketCompany {
  opportunities: Opportunity[];
}

export interface Opportunity {
  id: string;
  title: string;
  companyId: string;
  company: string;
  tier: number | null;
  priority: number | null;
  h1b: H1BStrength;
  location: string;
  areas: string[];
  zone: string | null;
  score: number;
  level: string;
  tags: string[];
  postedAt: string | null;
  firstSeenAt: string | null;
  isNew: boolean;
  sinceLastScan?: boolean;
  url: string;
  applyUrl: string;
  source: string | null;
  official: boolean;
  roleSponsorship: string | null;
  link?: LinkCheck | null;
}

export interface LinkCheck {
  status: "ok" | "dead" | "unknown";
  reason: string;
  checkedAt: string;
}

export interface LinkCheckProgress {
  running: boolean;
  total?: number;
  done?: number;
  dead?: number;
  finishedAt?: string | null;
  error?: string | null;
}

export interface RunSummary {
  runId: string;
  startedAt: string;
  finishedAt: string;
  scanned: number;
  succeeded: number;
  failed: number;
  skipped: number;
  imported: number;
  newJobs: number;
  closedJobs: number;
  startedHiring: string[];
  stoppedHiring: string[];
  sourceChanges: { company: string; from: string; to: string }[];
  needsAttention: number;
}

export interface MarketPulse {
  companies: number;
  matches: number;
  highMatch: number;
  newThisWeek: number;
  tier1Hiring: number;
  hiringCompanies: number;
  autoSearchable: number;
  autoSearchablePct: number;
  fresh24h: number;
  fresh24hPct: number;
  health: Record<StatusBucket, number>;
  lastScanAt: string | null;
  lastRun: RunSummary | null;
}

export interface AttentionRow {
  companyId: string;
  company: string;
  tier: number | null;
  priority: number | null;
  source: string;
  problem: string;
  reason: string;
  status: StatusBucket;
  lastSuccessAt: string | null;
  lastAttemptAt: string | null;
  url: string;
  otherSources: number;
}

export interface MarketHealth {
  sources: ({ source: string; total: number } & Partial<Record<StatusBucket, number>>)[];
  problems: { problem: string; count: number }[];
  needsAttention: AttentionRow[];
}

export interface RefreshProgress {
  marketId: string;
  running: boolean;
  runId?: string;
  phase?: "starting" | "detecting" | "scanning" | "importing" | "done" | "failed";
  startedAt?: string;
  finishedAt?: string | null;
  total?: number;
  done?: number;
  current?: string[];
  groups?: Record<string, { label: string; total: number; done: number }>;
  counts?: { succeeded: number; failed: number; skipped: number; detected: number; imported: number };
  error?: string | null;
  summary?: RunSummary | null;
}

export interface MarketOverview {
  market: MarketInfo;
  pulse: MarketPulse;
  strip: { kind: "new" | "hiring" | "none"; count: number; text: string } | null;
  companies: MarketCompany[];
  opportunities: Opportunity[];
  health: MarketHealth;
  refresh: RefreshProgress;
  links?: LinkCheckProgress;
  runs: RunSummary[];
}
