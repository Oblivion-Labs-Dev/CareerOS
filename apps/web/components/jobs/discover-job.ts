import type { JobGapAnalysis } from "./job-match-gap-panel";

export type DiscoverJob = {
  id: string;
  companyName: string;
  title: string;
  location: string;
  url: string;
  description?: string;
  relevancyScore: number;
  color: string;
  keywordsMatched: string[];
  gapAnalysis?: JobGapAnalysis;
  gapAnalysisMethod?: string;
  updatedAt?: string;
  salaryRange?: string;
  employmentType?: string;
  h1bStatus?: "likely" | "unlikely" | "unknown";
  h1bLabel?: string;
  h1bReason?: string;
  h1bSignals?: string[];
  freshness?: { hours_ago: number; label: string; badge_color: string };
};
