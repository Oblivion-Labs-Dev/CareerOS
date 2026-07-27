import type {
  CorpusReadiness,
  InterviewAnswerStatus,
  MetricVerification,
  ReviewerConcernStatus,
} from "@career-os/core";
import type { Accomplishment, EvidenceItem, PhaseOneAccomplishmentData } from "./types";
import { emptyPhaseOneData, phaseOneFromAccomplishment } from "./phase1-model";

export type CorpusQualityStatus =
  | "missing"
  | "weak"
  | "partial"
  | "strong"
  | "interview-ready"
  | "not-applicable"
  | "needs-verification";

export type SearchCategory =
  | "Accomplishments"
  | "Metrics"
  | "Skills"
  | "Evidence"
  | "Reviewer concerns"
  | "Interview questions";

export interface CorpusMetricView {
  id: string;
  name: string;
  value: string;
  unit?: string;
  source?: string;
  confidence: "low" | "medium" | "high";
  verification: MetricVerification;
  evidenceIds: string[];
}

export interface CorpusEvidenceView {
  id: string;
  name: string;
  type: string;
  url: string;
  relatedGapIds: string[];
}

export interface CorpusConcernView {
  id: string;
  reviewer: string;
  category: string;
  severity: "low" | "medium" | "high" | "critical";
  concern: string;
  status: ReviewerConcernStatus;
}

export interface CorpusQuestionView {
  id: string;
  question: string;
  interviewType: string;
  reviewerPersona: string;
  difficulty: "foundation" | "intermediate" | "advanced" | "expert";
  answerStatus: InterviewAnswerStatus;
  preparedAnswer?: string;
  confidence: number;
  qualityStatus?: CorpusQualityStatus;
  evidenceIds: string[];
  metricIds: string[];
  followUpQuestions: string[];
  reviewerFeedback: string[];
  practiceHistory: string[];
}

export interface CorpusResumeVariantView {
  id: string;
  name: string;
  content: string;
  status: "draft" | "published" | "archived";
}

export interface CorpusRecord {
  id: string;
  title: string;
  company: string;
  role: string;
  project: string;
  timePeriod: string;
  summary: string;
  currentBullet: string;
  technicalChallenge: string;
  architectureDecision: string;
  alternatives: string;
  tradeoffs: string;
  failureModes: string;
  reliabilityAndScale: string;
  reliabilityDetails: string;
  securityConsiderations: string;
  scaleDetails: string;
  businessImpact: string;
  engineeringImpact: string;
  leadership: string;
  crossTeamInfluence: string;
  mentorship: string;
  technologies: string[];
  domains: string[];
  concepts: string[];
  ownership: string;
  readiness: CorpusReadiness;
  completeness: number;
  roastResistance: number;
  impactScore: number;
  evidenceScore: number;
  architectureCovered: boolean;
  leadershipCovered: boolean;
  metrics: CorpusMetricView[];
  evidence: CorpusEvidenceView[];
  concerns: CorpusConcernView[];
  interviewQuestions: CorpusQuestionView[];
  resumeVariants: CorpusResumeVariantView[];
  linkedInVersion: string;
  portfolioVersion: string;
  missingInformation: string[];
  missingItemMetadata: Record<string, { priority: "high" | "medium" | "low"; researchLocation: string; notes: string }>;
  nextImprovement: string;
  qualityStatusOverrides: Partial<Record<string, CorpusQualityStatus>>;
  phaseOne: PhaseOneAccomplishmentData;
  updatedAt?: string;
  raw?: Accomplishment;
}

export interface CorpusProfile {
  fullName: string;
  currentTitle: string;
  targetRole: string;
  yearsExperience: string;
  primaryDomains: string[];
}

export interface NewAccomplishmentInput {
  title: string;
  company: string;
  role: string;
  timePeriod: string;
  summary: string;
  metricName?: string;
  metricValue?: string;
  technologies: string[];
}

export interface CorpusSummary {
  total: number;
  ready: number;
  missingMetrics: number;
  unansweredQuestions: number;
  evidenceCoverage: number;
  architectureCoverage: number;
  leadershipCoverage: number;
  resumeReadiness: number;
  interviewReadiness: number;
  atsReadiness: number;
  roastResistance: number;
  seniorSignal: number;
  staffSignal: number;
}

export interface CorpusSearchResult {
  id: string;
  category: SearchCategory;
  label: string;
  snippet: string;
  recordId: string;
  searchText: string;
}

function clampScore(value: number | undefined, fallback = 0): number {
  if (typeof value !== "number" || Number.isNaN(value)) return fallback;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function completionFromChecklist(accomplishment: Accomplishment): number {
  const checklist = accomplishment.completenessChecklist;
  if (!checklist) return 0;
  const values = Object.values(checklist);
  if (values.length === 0) return 0;
  return Math.round((values.filter(Boolean).length / values.length) * 100);
}

function readinessFromLegacy(accomplishment: Accomplishment, completeness: number): CorpusReadiness {
  if (accomplishment.completenessStatus === "Complete" || completeness >= 90) return "ready";
  if (accomplishment.completenessStatus === "Needs information") return "needs-input";
  if (completeness >= 65) return "review";
  return "draft";
}

function titleFromLegacy(accomplishment: Accomplishment): string {
  const project = accomplishment.project?.trim();
  if (project) return project;
  const summary = accomplishment.problemContext?.what?.trim() || accomplishment.resumeEvolution?.current?.trim();
  if (!summary) return "Untitled accomplishment";
  return summary.length > 72 ? `${summary.slice(0, 69)}...` : summary;
}

function reviewerFromQuestionCategory(category: string): string {
  const value = category.toLowerCase();
  if (value.includes("principal")) return "Principal engineer";
  if (value.includes("staff")) return "Staff engineer";
  if (value.includes("security")) return "Security reviewer";
  if (value.includes("reliab") || value.includes("sre")) return "SRE reviewer";
  if (value.includes("recruit")) return "Recruiter";
  if (value.includes("manager") || value.includes("behavior")) return "Hiring manager";
  if (value.includes("devil") || value.includes("red team")) return "Devil's advocate";
  return "Senior engineer";
}

function collectLegacyQuestions(accomplishment: Accomplishment): CorpusQuestionView[] {
  const direct = (accomplishment.missingQuestions ?? []).map((question) => ({
    id: question.id,
    question: question.question,
    interviewType: question.category || "Deep dive",
    reviewerPersona: reviewerFromQuestionCategory(question.category || "Deep dive"),
    difficulty: "advanced" as const,
    answerStatus: accomplishment.questionMetadata?.[question.id]?.answerStatus ?? (question.answer ? ("prepared" as const) : ("unanswered" as const)),
    preparedAnswer: question.answer,
    confidence: accomplishment.questionMetadata?.[question.id]?.confidence ?? (question.answer ? 60 : 0),
    qualityStatus: accomplishment.questionMetadata?.[question.id]?.qualityStatus,
    evidenceIds: accomplishment.questionMetadata?.[question.id]?.evidenceIds ?? [],
    metricIds: accomplishment.questionMetadata?.[question.id]?.metricIds ?? [],
    followUpQuestions: accomplishment.questionMetadata?.[question.id]?.followUpQuestions ?? [],
    reviewerFeedback: accomplishment.questionMetadata?.[question.id]?.reviewerFeedback ?? [],
    practiceHistory: accomplishment.questionMetadata?.[question.id]?.practiceHistory ?? [],
  }));

  const reviewerGroups = accomplishment.reviews?.interview?.questions;
  if (!reviewerGroups) return direct;

  const directIds = new Set(direct.map((question) => question.id));
  const generated = Object.entries(reviewerGroups).flatMap(([interviewType, questions]) =>
    (questions ?? []).map((question, index) => {
      const id = `${accomplishment.id}-review-${interviewType}-${index}`;
      const metadata = accomplishment.questionMetadata?.[id];
      return {
      id,
      question,
      interviewType,
      reviewerPersona: accomplishment.reviews.interview.roleName || "Technical reviewer",
      difficulty: "advanced" as const,
      answerStatus: metadata?.answerStatus ?? "unanswered" as const,
      confidence: metadata?.confidence ?? 0,
      qualityStatus: metadata?.qualityStatus,
      evidenceIds: metadata?.evidenceIds ?? [],
      metricIds: metadata?.metricIds ?? [],
      followUpQuestions: metadata?.followUpQuestions ?? [],
      reviewerFeedback: metadata?.reviewerFeedback ?? [],
      practiceHistory: metadata?.practiceHistory ?? [],
    };}).filter((question) => !directIds.has(question.id)),
  );

  return [...direct, ...generated];
}

function collectLegacyConcerns(accomplishment: Accomplishment): CorpusConcernView[] {
  const architecture = (accomplishment.reviews?.principal?.architectureConcerns ?? []).map((concern, index) => ({
    id: `${accomplishment.id}-architecture-${index}`,
    reviewer: accomplishment.reviews.principal.roleName || "Architecture reviewer",
    category: "Architecture",
    severity: "high" as const,
    concern,
    status: "unanswered" as const,
  }));

  const rejection = (accomplishment.reviews?.devil?.reasonsToReject ?? []).map((concern, index) => ({
    id: `${accomplishment.id}-rejection-${index}`,
    reviewer: accomplishment.reviews.devil.roleName || "Devil's advocate",
    category: "Rejection risk",
    severity: "critical" as const,
    concern,
    status: "unanswered" as const,
  }));

  return [...architecture, ...rejection];
}

export function normalizeAccomplishment(accomplishment: Accomplishment): CorpusRecord {
  const completeness = completionFromChecklist(accomplishment);
  const evidence = (accomplishment.evidence ?? []).map((item, index) => ({
    id: `${accomplishment.id}-evidence-${index}`,
    name: item.name,
    type: item.type,
    url: item.url,
    relatedGapIds: accomplishment.evidenceMetadata?.[`${accomplishment.id}-evidence-${index}`]?.relatedGapIds ?? [],
  }));
  const metrics = (accomplishment.scaleMetrics ?? []).map((metric, index) => {
    const id = `${accomplishment.id}-metric-${index}`;
    const metadata = accomplishment.metricMetadata?.[id];
    return {
      id,
      name: metric.metric,
      value: metric.value,
      source: metadata?.source,
      confidence: metadata?.confidence ?? "medium" as const,
      verification: metadata?.verification ?? "unverified" as const,
      evidenceIds: metadata?.evidenceIds ?? [],
    };
  });
  const questions = collectLegacyQuestions(accomplishment);
  const roadmap = accomplishment.roadmap;
  const missingInformation = [...new Set([
    ...(accomplishment.missingInformation ?? []),
    ...(roadmap?.missingMetrics ?? []),
    ...(roadmap?.missingArchitecture ?? []),
    ...(roadmap?.missingLeadershipEvidence ?? []),
  ])];

  const role = accomplishment.roleDetails?.responsibility || "";
  const businessScore = clampScore(accomplishment.confidenceScores?.businessImpact);
  const engineeringScore = clampScore(accomplishment.confidenceScores?.engineeringImpact);

  return {
    id: accomplishment.id,
    title: titleFromLegacy(accomplishment),
    company: accomplishment.company || "",
    role,
    project: accomplishment.project || "",
    timePeriod: accomplishment.timePeriod || "",
    summary: accomplishment.problemContext?.what || "",
    currentBullet: accomplishment.resumeEvolution?.current || accomplishment.problemContext?.what || "",
    technicalChallenge: accomplishment.challenges?.join("\n") || "",
    architectureDecision: accomplishment.decisions?.what || "",
    alternatives: accomplishment.decisions?.alternatives?.join("\n") || "",
    tradeoffs: accomplishment.decisions?.tradeoffs || "",
    failureModes: accomplishment.decisions?.failureConsiderations || "",
    reliabilityAndScale: [accomplishment.systemDesign?.dataFlow, ...(accomplishment.scaleMetrics ?? []).map((metric) => `${metric.metric}: ${metric.value}`)].filter(Boolean).join("\n"),
    reliabilityDetails: accomplishment.reliabilityDetails || accomplishment.systemDesign?.eventFlow || "",
    securityConsiderations: accomplishment.securityConsiderations || "",
    scaleDetails: accomplishment.scaleDetails || (accomplishment.scaleMetrics ?? []).map((metric) => `${metric.metric}: ${metric.value}`).join("\n"),
    businessImpact: accomplishment.impact?.business?.join("\n") || "",
    engineeringImpact: accomplishment.impact?.engineering?.join("\n") || "",
    leadership: accomplishment.leadership?.join("\n") || "",
    crossTeamInfluence: accomplishment.crossTeamInfluence || "",
    mentorship: accomplishment.mentorship || "",
    technologies: accomplishment.techStack ?? accomplishment.technologies ?? [],
    domains: accomplishment.concepts?.slice(0, 4) ?? [],
    concepts: accomplishment.concepts ?? [],
    ownership: accomplishment.roleDetails?.ownership || "",
    readiness: readinessFromLegacy(accomplishment, completeness),
    completeness,
    roastResistance: clampScore(accomplishment.roastResistanceScore),
    impactScore: businessScore || engineeringScore ? Math.round((businessScore + engineeringScore) / 2) : 0,
    evidenceScore: clampScore(accomplishment.confidenceScores?.evidence, evidence.length > 0 ? 50 : 0),
    architectureCovered: Boolean(accomplishment.completenessChecklist?.architectureExplained),
    leadershipCovered: Boolean(accomplishment.completenessChecklist?.leadershipShown),
    metrics,
    evidence,
    concerns: collectLegacyConcerns(accomplishment),
    interviewQuestions: questions,
    resumeVariants: [
      { id: `${accomplishment.id}-current`, name: "Current", content: accomplishment.resumeEvolution?.current || "", status: "published" },
      { id: `${accomplishment.id}-improved`, name: "Improved", content: accomplishment.resumeEvolution?.improved || "", status: "draft" },
      { id: `${accomplishment.id}-ats`, name: "ATS", content: accomplishment.resumeEvolution?.atsOptimized || "", status: "draft" },
    ].filter((variant) => Boolean(variant.content)) as CorpusResumeVariantView[],
    linkedInVersion: accomplishment.resumeEvolution?.linkedin || "",
    portfolioVersion: accomplishment.portfolioVersion || "",
    missingInformation,
    missingItemMetadata: Object.fromEntries(Object.entries(accomplishment.missingItemMetadata ?? {}).map(([id, metadata]) => [id, {
      priority: metadata.priority ?? "medium",
      researchLocation: metadata.researchLocation ?? "",
      notes: metadata.notes ?? "",
    }])),
    nextImprovement: roadmap?.top3Improvements?.[0] || "Review the record and add the next missing piece of evidence.",
    qualityStatusOverrides: accomplishment.qualityStatusOverrides ?? {},
    phaseOne: phaseOneFromAccomplishment(accomplishment),
    updatedAt: accomplishment.updatedAt,
    raw: accomplishment,
  };
}

export function createLegacyAccomplishmentDraft(input: NewAccomplishmentInput): Accomplishment {
  const id = typeof globalThis.crypto?.randomUUID === "function"
    ? globalThis.crypto.randomUUID()
    : `accomplishment-${Date.now()}`;
  const hasMetric = Boolean(input.metricName?.trim() && input.metricValue?.trim());
  const legacy = {
    id,
    company: input.company.trim(),
    team: "",
    project: input.title.trim(),
    timePeriod: input.timePeriod.trim(),
    techStack: input.technologies,
    status: "current",
    problemContext: {
      what: input.summary.trim(),
      why: "",
      who: "",
      businessContext: "",
      engineeringContext: "",
    },
    roleDetails: {
      responsibility: input.role.trim(),
      ownership: "",
      contributions: [],
    },
    challenges: [],
    decisions: {
      what: "",
      why: "",
      alternatives: [],
      tradeoffs: "",
      rejectedApproaches: [],
      failureConsiderations: "",
    },
    reliabilityDetails: "",
    securityConsiderations: "",
    scaleDetails: hasMetric ? `${input.metricName!.trim()}: ${input.metricValue!.trim()}` : "",
    systemDesign: {
      diagramType: "text",
      diagramContent: "",
      dataFlow: "",
      eventFlow: "",
    },
    concepts: [],
    technologies: input.technologies,
    scaleMetrics: hasMetric ? [{ metric: input.metricName!.trim(), value: input.metricValue!.trim() }] : [],
    impact: { business: [], engineering: [] },
    leadership: [],
    crossTeamInfluence: "",
    mentorship: "",
    completenessChecklist: {
      problemExplained: Boolean(input.summary.trim()),
      businessProblemExplained: false,
      technicalProblemExplained: false,
      architectureExplained: false,
      tradeoffsExplained: false,
      scaleIncluded: hasMetric,
      metricsIncluded: hasMetric,
      impactIncluded: false,
      leadershipShown: false,
      ownershipShown: false,
      decisionShown: false,
      failureHandlingExplained: false,
      performanceExplained: false,
      securityExplained: false,
      reliabilityExplained: false,
      devProductivityExplained: false,
      platformThinkingShown: false,
      operationalOwnershipShown: false,
      customerImpactShown: false,
      businessImpactShown: false,
      evidenceAttached: false,
      interviewStoryAvailable: false,
      diagramAvailable: false,
      rfcAttached: false,
    },
    completenessStatus: "Needs information",
    missingQuestions: [],
    resumeEvolution: {
      current: input.summary.trim(),
      improved: "",
      top10Percent: "",
      top1Percent: "",
      atsOptimized: "",
      hmFavorite: "",
      principalFavorite: "",
      mostTechnical: "",
      mostBusiness: "",
      mostConcise: "",
      interview: "",
      linkedin: "",
      star: "",
    },
    confidenceScores: {
      truth: 80,
      metric: hasMetric ? 35 : 0,
      architecture: 0,
      leadership: 0,
      businessImpact: 0,
      engineeringImpact: 0,
      evidence: 0,
      resume: 20,
      interview: 0,
    },
    roastResistanceScore: 20,
    roastDeductions: [],
    roadmap: {
      top3Improvements: ["Clarify personal ownership", "Add supporting evidence", "Document the decision and its tradeoffs"],
      missingMetrics: hasMetric ? [] : ["Add a truthful outcome metric"],
      missingArchitecture: ["Document the primary decision"],
      missingEngineeringDetails: [],
      missingBusinessImpact: ["Explain why the outcome mattered"],
      missingLeadershipEvidence: ["Clarify your influence and ownership"],
      missingInterviewStories: ["Prepare a concise deep-dive answer"],
      missingDocumentation: ["Attach a safe source or artifact"],
    },
    qualityStatusOverrides: {},
    missingInformation: [],
    missingItemMetadata: {},
    metricMetadata: {},
    questionMetadata: {},
    phaseOne: emptyPhaseOneData(),
  };
  return legacy as unknown as Accomplishment;
}

export function applyRecordToLegacy(record: CorpusRecord): Accomplishment | undefined {
  const raw = record.raw;
  if (!raw) return undefined;
  return {
    ...raw,
    company: record.company,
    project: record.project,
    timePeriod: record.timePeriod,
    techStack: record.technologies,
    concepts: record.concepts,
    problemContext: { ...raw.problemContext, what: record.summary },
    roleDetails: { ...raw.roleDetails, ownership: record.ownership, responsibility: record.role },
    challenges: record.technicalChallenge.split("\n").map((value) => value.trim()).filter(Boolean),
    decisions: {
      ...raw.decisions,
      what: record.architectureDecision,
      alternatives: record.alternatives.split("\n").map((value) => value.trim()).filter(Boolean),
      tradeoffs: record.tradeoffs,
      failureConsiderations: record.failureModes,
    },
    reliabilityDetails: record.reliabilityDetails,
    securityConsiderations: record.securityConsiderations,
    scaleDetails: record.scaleDetails,
    impact: {
      ...raw.impact,
      business: record.businessImpact.split("\n").map((value) => value.trim()).filter(Boolean),
      engineering: record.engineeringImpact.split("\n").map((value) => value.trim()).filter(Boolean),
    },
    leadership: record.leadership.split("\n").map((value) => value.trim()).filter(Boolean),
    crossTeamInfluence: record.crossTeamInfluence,
    mentorship: record.mentorship,
    evidence: record.evidence.map((item) => ({
      name: item.name,
      type: (["rfc", "pr", "doc", "screenshot", "dashboard"] as string[]).includes(item.type)
        ? item.type as EvidenceItem["type"]
        : "doc",
      url: item.url,
    })),
    evidenceMetadata: Object.fromEntries(record.evidence.map((item) => [item.id, { relatedGapIds: item.relatedGapIds }])),
    portfolioVersion: record.portfolioVersion,
    resumeEvolution: {
      ...raw.resumeEvolution,
      current: record.currentBullet,
      linkedin: record.linkedInVersion,
    },
    scaleMetrics: record.metrics.map((metric) => ({ metric: metric.name, value: metric.value })),
    qualityStatusOverrides: Object.fromEntries(
      Object.entries(record.qualityStatusOverrides).filter((entry): entry is [string, CorpusQualityStatus] => entry[1] !== undefined),
    ),
    missingInformation: record.missingInformation,
    missingItemMetadata: record.missingItemMetadata,
    phaseOne: record.phaseOne,
    metricMetadata: Object.fromEntries(record.metrics.map((metric) => [metric.id, {
      confidence: metric.confidence,
      verification: metric.verification,
      source: metric.source,
      evidenceIds: metric.evidenceIds,
    }])),
    questionMetadata: Object.fromEntries(record.interviewQuestions.map((question) => [question.id, {
      answerStatus: question.answerStatus,
      confidence: question.confidence,
      qualityStatus: question.qualityStatus,
      evidenceIds: question.evidenceIds,
      metricIds: question.metricIds,
      followUpQuestions: question.followUpQuestions,
      reviewerFeedback: question.reviewerFeedback,
      practiceHistory: question.practiceHistory,
    }])),
    missingQuestions: record.interviewQuestions.map((question) => {
      const original = raw.missingQuestions?.find((candidate) => candidate.id === question.id);
      return {
        ...original,
        id: question.id,
        question: question.question,
        category: question.interviewType,
        answer: question.preparedAnswer,
      };
    }),
    completenessChecklist: {
      ...raw.completenessChecklist,
      problemExplained: Boolean(record.summary.trim()),
      architectureExplained: Boolean(record.architectureDecision.trim()),
      tradeoffsExplained: Boolean(record.tradeoffs.trim()),
      scaleIncluded: Boolean(record.scaleDetails.trim() || record.metrics.length),
      metricsIncluded: record.metrics.length > 0,
      impactIncluded: Boolean(record.businessImpact.trim() || record.engineeringImpact.trim()),
      leadershipShown: Boolean(record.leadership.trim()),
      ownershipShown: Boolean(record.ownership.trim()),
      decisionShown: Boolean(record.architectureDecision.trim()),
      failureHandlingExplained: Boolean(record.failureModes.trim()),
      securityExplained: Boolean(record.securityConsiderations.trim()),
      reliabilityExplained: Boolean(record.reliabilityDetails.trim()),
      evidenceAttached: record.evidence.length > 0,
      interviewStoryAvailable: record.interviewQuestions.some((question) => Boolean(question.preparedAnswer?.trim())),
    },
  };
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return Math.round(values.reduce((sum, value) => sum + value, 0) / values.length);
}

export function summarizeCorpus(records: CorpusRecord[]): CorpusSummary {
  const total = records.length;
  const percentage = (count: number) => (total === 0 ? 0 : Math.round((count / total) * 100));
  const allQuestions = records.flatMap((record) => record.interviewQuestions);
  const answeredQuestions = allQuestions.filter((question) => question.answerStatus !== "unanswered").length;

  return {
    total,
    ready: records.filter((record) => record.readiness === "ready").length,
    missingMetrics: records.filter((record) => record.metrics.length === 0).length,
    unansweredQuestions: allQuestions.length - answeredQuestions,
    evidenceCoverage: percentage(records.filter((record) => record.evidence.length > 0).length),
    architectureCoverage: percentage(records.filter((record) => record.architectureCovered).length),
    leadershipCoverage: percentage(records.filter((record) => record.leadershipCovered).length),
    resumeReadiness: average(records.map((record) => record.completeness)),
    interviewReadiness: allQuestions.length === 0 ? 0 : Math.round((answeredQuestions / allQuestions.length) * 100),
    atsReadiness: average(records.map((record) => Math.round((record.completeness + record.roastResistance) / 2))),
    roastResistance: average(records.map((record) => record.roastResistance)),
    seniorSignal: average(records.map((record) => Math.round((record.completeness + record.impactScore) / 2))),
    staffSignal: average(records.map((record) => Math.round((record.impactScore + (record.leadershipCovered ? 100 : 35)) / 2))),
  };
}

export function buildSearchIndex(records: CorpusRecord[]): CorpusSearchResult[] {
  return records.flatMap((record) => {
    const presetTags = [
      record.metrics.length === 0 ? "__missing_metrics__" : "",
      !record.ownership.trim() || record.ownership.trim().length < 40 ? "__weak_ownership__" : "",
      record.leadership.trim() || record.impactScore >= 75 ? "__staff_level__" : "",
      record.interviewQuestions.some((question) => question.answerStatus === "unanswered") ? "__unanswered_questions__" : "",
      record.evidence.length === 0 ? "__missing_evidence__" : "",
      record.roastResistance < 60 ? "__low_roast_resistance__" : "",
      record.readiness === "ready" ? "__ready_for_resume__" : "",
      record.concerns.some((concern) => concern.status === "unanswered" || concern.status === "investigating") ? "__needs_review__" : "",
    ].filter(Boolean);
    const base: CorpusSearchResult[] = [
      {
        id: `accomplishment-${record.id}`,
        category: "Accomplishments",
        label: record.title,
        snippet: `${record.company} · ${record.currentBullet || record.summary}`,
        recordId: record.id,
        searchText: [
          record.title,
          record.company,
          record.role,
          record.project,
          record.timePeriod,
          record.summary,
          record.currentBullet,
          record.ownership,
          record.technicalChallenge,
          record.architectureDecision,
          record.tradeoffs,
          record.failureModes,
          record.reliabilityDetails,
          record.securityConsiderations,
          record.scaleDetails,
          record.businessImpact,
          record.engineeringImpact,
          record.leadership,
          record.linkedInVersion,
          record.portfolioVersion,
          ...record.technologies,
          ...record.domains,
          ...record.concepts,
          ...record.missingInformation,
          ...presetTags,
        ].join(" "),
      },
    ];

    const metrics = record.metrics.map((metric) => ({
      id: `metric-${metric.id}`,
      category: "Metrics" as const,
      label: `${metric.name}: ${metric.value}`,
      snippet: `${record.title} · ${metric.verification.replace("-", " ")}`,
      recordId: record.id,
      searchText: `${metric.name} ${metric.value} ${metric.source ?? ""} ${record.company} ${record.project}`,
    }));
    const skills = record.technologies.map((skill, index) => ({
      id: `skill-${record.id}-${index}`,
      category: "Skills" as const,
      label: skill,
      snippet: `${record.company} · ${record.title}`,
      recordId: record.id,
      searchText: `${skill} ${record.company} ${record.project} ${record.currentBullet}`,
    }));
    const evidence = record.evidence.map((item) => ({
      id: `evidence-${item.id}`,
      category: "Evidence" as const,
      label: item.name,
      snippet: `${item.type} · ${record.title}`,
      recordId: record.id,
      searchText: `${item.name} ${item.type} ${record.company} ${record.project}`,
    }));
    const concerns = record.concerns.map((concern) => ({
      id: `concern-${concern.id}`,
      category: "Reviewer concerns" as const,
      label: concern.concern,
      snippet: `${concern.reviewer} · ${record.title}`,
      recordId: record.id,
      searchText: `${concern.concern} ${concern.reviewer} ${concern.category} ${record.company}`,
    }));
    const questions = record.interviewQuestions.map((question) => ({
      id: `question-${question.id}`,
      category: "Interview questions" as const,
      label: question.question,
      snippet: `${question.interviewType} · ${record.title}`,
      recordId: record.id,
      searchText: `${question.question} ${question.interviewType} ${question.reviewerPersona} ${record.company}`,
    }));

    return [...base, ...metrics, ...skills, ...evidence, ...concerns, ...questions];
  });
}

export function searchCorpus(index: CorpusSearchResult[], query: string, category?: SearchCategory): CorpusSearchResult[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const presetTag = ({
    "missing metrics": "__missing_metrics__",
    "weak ownership": "__weak_ownership__",
    "staff-level accomplishments": "__staff_level__",
    "unanswered interview questions": "__unanswered_questions__",
    "missing evidence": "__missing_evidence__",
    "low roast resistance": "__low_roast_resistance__",
    "ready for resume": "__ready_for_resume__",
    "needs review": "__needs_review__",
  } as Record<string, string>)[normalizedQuery];
  const terms = presetTag ? [presetTag] : normalizedQuery.split(/\s+/).filter(Boolean);
  if (terms.length === 0) return [];
  return index
    .filter((result) => !category || result.category === category)
    .map((result) => {
      const text = result.searchText.toLocaleLowerCase();
      const score = terms.reduce((sum, term) => sum + (text.includes(term) ? 1 : 0), 0);
      return { result, score };
    })
    .filter(({ score }) => score > 0)
    .sort((left, right) => right.score - left.score || left.result.label.localeCompare(right.result.label))
    .map(({ result }) => result)
    .slice(0, 60);
}
