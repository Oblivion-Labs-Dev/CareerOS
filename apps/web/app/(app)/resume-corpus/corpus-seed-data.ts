import initialResumeCorpus from "../../../../../data/resume-corpus-initial.json";
import type { CorpusRecord } from "./corpus-model";

interface InitialMetric {
  name: string;
  value: string;
  source?: string;
  verification?: "unverified" | "needs-evidence" | "verified";
}

interface InitialResumeCorpusItem {
  id: string;
  company: string;
  title: string;
  currentBullet: string;
  problem?: string;
  businessContext?: string;
  technicalContext?: string;
  tools?: string[];
  ownership?: string;
  scale?: string[];
  impact?: string;
  architectureDecision?: string;
  evidence?: string[];
  metrics?: InitialMetric[];
  missing?: string[];
}

function completionFor(item: InitialResumeCorpusItem): number {
  const signals = [
    item.problem || item.currentBullet,
    item.businessContext,
    item.technicalContext,
    item.ownership,
    item.architectureDecision,
    item.scale?.length || item.metrics?.length,
    item.impact,
    item.tools?.length,
    item.evidence?.length,
  ];
  return Math.round((signals.filter(Boolean).length / signals.length) * 100);
}

export function initialCorpusItemToRecord(item: InitialResumeCorpusItem): CorpusRecord {
  const metrics = item.metrics ?? [];
  const evidence = item.evidence ?? [];
  const missingInformation = item.missing ?? [];
  const completeness = completionFor(item);

  return {
    id: item.id,
    title: item.title,
    company: item.company,
    role: item.ownership ?? "",
    project: item.title,
    timePeriod: "",
    summary: item.problem ?? item.currentBullet,
    currentBullet: item.currentBullet,
    technicalChallenge: item.technicalContext ?? "",
    architectureDecision: item.architectureDecision ?? "",
    alternatives: "",
    tradeoffs: "",
    failureModes: "",
    reliabilityAndScale: (item.scale ?? []).join(" ? "),
    reliabilityDetails: "",
    securityConsiderations: "",
    scaleDetails: (item.scale ?? []).join("\n"),
    businessImpact: item.impact ?? "",
    engineeringImpact: "",
    leadership: "",
    crossTeamInfluence: "",
    mentorship: "",
    technologies: item.tools ?? [],
    domains: [],
    concepts: [],
    ownership: item.ownership ?? "",
    readiness: missingInformation.length > 0 ? "needs-input" : completeness >= 90 ? "ready" : "review",
    completeness,
    roastResistance: Math.max(10, Math.min(70, completeness - missingInformation.length * 2)),
    impactScore: item.impact ? 55 : 0,
    evidenceScore: evidence.length > 0 ? 35 : 0,
    architectureCovered: Boolean(item.architectureDecision),
    leadershipCovered: false,
    metrics: metrics.map((metric, index) => ({
      id: `${item.id}-metric-${index}`,
      name: metric.name,
      value: metric.value,
      source: metric.source,
      confidence: "medium",
      verification: metric.verification ?? "needs-evidence",
    })),
    evidence: evidence.map((name, index) => ({
      id: `${item.id}-evidence-${index}`,
      name,
      type: "document",
      url: "",
      relatedGapIds: [],
    })),
    concerns: [],
    interviewQuestions: [],
    resumeVariants: [
      {
        id: `${item.id}-current`,
        name: "Current",
        content: item.currentBullet,
        status: "published",
      },
    ],
    linkedInVersion: "",
    portfolioVersion: "",
    missingInformation,
    nextImprovement: missingInformation[0] ?? "Attach evidence and prepare the interview deep dive.",
    qualityStatusOverrides: {},
  };
}

export const INITIAL_CORPUS_RECORDS: CorpusRecord[] = (
  initialResumeCorpus as InitialResumeCorpusItem[]
).map(initialCorpusItemToRecord);
