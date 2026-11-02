import type { CorpusQualityStatus, CorpusRecord, CorpusQuestionView } from "./corpus-model";

/** Unified quality status for fields, answers, metrics, and concerns. */
export type QualityStatus = CorpusQualityStatus;

export type GapCategoryId =
  | "problem-context"
  | "ownership"
  | "technical-challenge"
  | "architecture"
  | "alternatives"
  | "tradeoffs"
  | "scale"
  | "business-impact"
  | "engineering-impact"
  | "reliability"
  | "security"
  | "failure-handling"
  | "leadership"
  | "cross-team"
  | "mentorship"
  | "evidence"
  | "metric-validation"
  | "interview-story"
  | "follow-up-readiness";

export interface GapCategoryDefinition {
  id: GapCategoryId;
  label: string;
  sectionId?: string;
}

export const GAP_CATEGORIES: GapCategoryDefinition[] = [
  { id: "problem-context", label: "Problem context", sectionId: "context" },
  { id: "ownership", label: "Personal ownership", sectionId: "ownership" },
  { id: "technical-challenge", label: "Technical challenge", sectionId: "challenge" },
  { id: "architecture", label: "Architecture", sectionId: "architecture" },
  { id: "alternatives", label: "Alternatives", sectionId: "architecture" },
  { id: "tradeoffs", label: "Tradeoffs", sectionId: "architecture" },
  { id: "scale", label: "Scale", sectionId: "scale" },
  { id: "business-impact", label: "Business impact", sectionId: "business" },
  { id: "engineering-impact", label: "Engineering impact", sectionId: "engineering" },
  { id: "reliability", label: "Reliability", sectionId: "reliability" },
  { id: "security", label: "Security", sectionId: "security" },
  { id: "failure-handling", label: "Failure handling", sectionId: "failure" },
  { id: "leadership", label: "Leadership", sectionId: "leadership" },
  { id: "cross-team", label: "Cross-team influence", sectionId: "leadership" },
  { id: "mentorship", label: "Mentorship", sectionId: "leadership" },
  { id: "evidence", label: "Evidence", sectionId: "evidence" },
  { id: "metric-validation", label: "Metric validation", sectionId: "scale" },
  { id: "interview-story", label: "Interview story", sectionId: "interview" },
  { id: "follow-up-readiness", label: "Follow-up readiness", sectionId: "interview" },
];

export type HeatmapDimension =
  | "ownership"
  | "architecture"
  | "scale"
  | "impact"
  | "leadership"
  | "reliability"
  | "security"
  | "evidence"
  | "interview-readiness"
  | "resume-readiness";

export const HEATMAP_DIMENSIONS: Array<{ id: HeatmapDimension; label: string }> = [
  { id: "ownership", label: "Ownership" },
  { id: "architecture", label: "Architecture" },
  { id: "scale", label: "Scale" },
  { id: "impact", label: "Impact" },
  { id: "leadership", label: "Leadership" },
  { id: "reliability", label: "Reliability" },
  { id: "security", label: "Security" },
  { id: "evidence", label: "Evidence" },
  { id: "interview-readiness", label: "Interview" },
  { id: "resume-readiness", label: "Resume" },
];

export interface GapItem {
  id: GapCategoryId;
  category: string;
  status: QualityStatus;
  missingDetail: string;
  whyItMatters: string;
  question: string;
  currentAnswer: string;
  suggestedAction: string;
  resumeImpact: "high" | "medium" | "low";
  interviewRisk: "high" | "medium" | "low";
  effort: "low" | "medium" | "high";
  relatedConcernId?: string;
  reviewerPersona?: string;
}

export interface BulletReadinessSummary {
  overallStatus: QualityStatus;
  missingCount: number;
  weakCount: number;
  partialCount: number;
  strongCount: number;
  interviewReadyCount: number;
  needsVerificationCount: number;
  notApplicableCount: number;
  completionPercent: number;
  roastResistance: number;
  topGap: string;
  topGapCategory: GapCategoryId;
  segments: Array<{ status: QualityStatus; count: number }>;
}

export interface AnswerQualityAssessment {
  status: QualityStatus;
  score: number;
  strengths: string[];
  weaknesses: string[];
  missingElements: string[];
  improvementPrompt?: string;
  personaNotes?: string;
  dimensions: Array<{
    id: "directness" | "technical-depth" | "ownership-clarity" | "architecture-reasoning" | "tradeoff-awareness" | "scale" | "impact" | "evidence" | "follow-up-readiness" | "credibility";
    label: string;
    status: QualityStatus;
    reason: string;
  }>;
}

export interface GeneratedQuestion {
  id: string;
  question: string;
  reviewerPersona: string;
  interviewType: string;
  difficulty: CorpusQuestionView["difficulty"];
  trigger: string;
  category: GapCategoryId;
}

export interface ResearchItem {
  id: string;
  recordId: string;
  recordTitle: string;
  missingFact: string;
  whyItMatters: string;
  whereToLook: string;
  suggestedSource: string;
  priority: "high" | "medium" | "low";
  status: "open" | "found" | "verified" | "estimated" | "unavailable" | "not-disclosable" | "not-worth";
  notes?: string;
}

export interface PriorityItem {
  id: string;
  recordId: string;
  recordTitle: string;
  type: "gap" | "question" | "concern" | "research";
  title: string;
  whyItMatters: string;
  reviewers: string[];
  resumeImpact: "high" | "medium" | "low";
  interviewRisk: "high" | "medium" | "low";
  benefit: string;
  likelihood: "high" | "medium" | "low";
  evidenceAvailability: "high" | "medium" | "low";
  effort: "low" | "medium" | "high";
  roleRelevance: "high" | "medium" | "low";
  reviewerCount: number;
  score: number;
  gapCategory?: GapCategoryId;
  questionId?: string;
}

export interface ResumeBulletReadiness {
  recordId: string;
  label: string;
  indicator: "ready" | "strong-unverified" | "missing-architecture" | "weak-ownership" | "interview-risk" | "not-recommended";
  message: string;
  blockReason?: string;
}

const GENERIC_PHRASES = [
  "helped",
  "worked on",
  "was involved",
  "contributed to",
  "participated",
  "assisted",
  "supported",
  "collaborated",
  "not documented",
  "various",
  "multiple",
  "several",
];

function isEmpty(value: string | undefined): boolean {
  return !value?.trim();
}

function isWeakText(value: string | undefined): boolean {
  if (isEmpty(value)) return false;
  const lower = value!.toLowerCase();
  if (value!.trim().length < 40) return true;
  return GENERIC_PHRASES.some((phrase) => lower.includes(phrase));
}

function fieldStatus(value: string | undefined, minStrong = 80): QualityStatus {
  if (isEmpty(value)) return "missing";
  const len = value!.trim().length;
  if (isWeakText(value)) return "weak";
  if (len < minStrong) return "partial";
  return "strong";
}

function impactRank(value: "high" | "medium" | "low"): number {
  return value === "high" ? 3 : value === "medium" ? 2 : 1;
}

function statusRank(status: QualityStatus): number {
  const order: QualityStatus[] = ["missing", "needs-verification", "weak", "partial", "strong", "interview-ready", "not-applicable"];
  return order.indexOf(status);
}

export function evaluateField(value: string | undefined, options?: { notApplicable?: boolean }): QualityStatus {
  if (options?.notApplicable) return "not-applicable";
  return fieldStatus(value);
}

export function evaluateMetric(record: CorpusRecord): QualityStatus {
  if (record.metrics.length === 0) return "missing";
  if (record.metrics.some((metric) => !metric.value?.trim())) return "missing";
  if (record.metrics.some((metric) => metric.verification === "needs-evidence")) return "needs-verification";
  if (record.metrics.some((metric) => metric.verification === "unverified" && /\d|%|\bx\b/i.test(metric.value))) return "needs-verification";
  if (record.metrics.every((metric) => metric.verification === "verified")) return "strong";
  if (record.metrics.some((metric) => metric.verification === "verified")) return "partial";
  return record.metrics.every((metric) => metric.value.trim().length >= 3) ? "partial" : "weak";
}

export function evaluateQuestionQuality(question: CorpusQuestionView, record: CorpusRecord): AnswerQualityAssessment {
  const answer = question.preparedAnswer?.trim() ?? "";
  const explicitStatus = question.qualityStatus;
  const persona = question.reviewerPersona.toLowerCase();
  const linkedEvidence = question.evidenceIds.filter((id) => record.evidence.some((item) => item.id === id));
  const linkedMetrics = question.metricIds
    .map((id) => record.metrics.find((metric) => metric.id === id))
    .filter((metric): metric is CorpusRecord["metrics"][number] => Boolean(metric));
  const makeDimension = (
    id: AnswerQualityAssessment["dimensions"][number]["id"],
    label: string,
    status: QualityStatus,
    reason: string,
  ): AnswerQualityAssessment["dimensions"][number] => ({ id, label, status, reason });

  const dimensionLabels: Array<[AnswerQualityAssessment["dimensions"][number]["id"], string]> = [
    ["directness", "Directness"], ["technical-depth", "Technical depth"], ["ownership-clarity", "Ownership clarity"],
    ["architecture-reasoning", "Architecture reasoning"], ["tradeoff-awareness", "Tradeoff awareness"], ["scale", "Scale"],
    ["impact", "Impact"], ["evidence", "Evidence"], ["follow-up-readiness", "Follow-up readiness"], ["credibility", "Credibility"],
  ];

  if (explicitStatus === "not-applicable") {
    return {
      status: "not-applicable",
      score: 100,
      strengths: [],
      weaknesses: [],
      missingElements: [],
      improvementPrompt: "This question is intentionally excluded from readiness calculations.",
      dimensions: dimensionLabels.map(([id, label]) => makeDimension(id, label, "not-applicable", "Marked not applicable.")),
    };
  }

  if (!answer) {
    const dimensions = dimensionLabels.map(([id, label]) => makeDimension(id, label, "missing", `No ${label.toLowerCase()} can be assessed until an answer exists.`));
    return {
      status: "missing",
      score: 0,
      strengths: [],
      weaknesses: ["No answer recorded"],
      missingElements: ["Direct response", "Supporting metric", "Ownership statement"],
      improvementPrompt: "Write a direct answer with ownership, one tradeoff, and one metric.",
      personaNotes: `Unanswered ${question.reviewerPersona} question — high interview risk.`,
      dimensions,
    };
  }

  const hasTechnicalDepth = /architecture|system|service|database|queue|cache|retry|latency|throughput|deployment|workflow|api|schema|failure/i.test(answer);
  const hasOwnership = /\b(i|my)\b|\bled\b|\bowned\b|\bdesigned\b|\bdrove\b|\bdecided\b/i.test(answer);
  const hasReasoning = /because|therefore|so that|chose|decided|rationale|constraint/i.test(answer);
  const hasTradeoff = /tradeoff|trade-off|instead|alternative|cost|accepted|sacrific|downside/i.test(answer);
  const hasScale = /\d|%|\bx\b|\btps\b|\brps\b|\bms\b|region|request|user|volume|latency/i.test(answer) || linkedMetrics.length > 0;
  const hasImpact = /impact|improv|reduc|increas|saved|revenue|customer|adoption|reliab|velocity|cost/i.test(answer);
  const unverifiedLinkedMetric = linkedMetrics.some((metric) => metric.verification !== "verified");
  const generic = isWeakText(answer);

  const dimensions: AnswerQualityAssessment["dimensions"] = [
    makeDimension("directness", "Directness", answer.length < 60 ? "weak" : answer.length < 110 ? "partial" : "strong", answer.length < 60 ? "The answer is too brief to resolve the question." : "The response directly addresses the prompt."),
    makeDimension("technical-depth", "Technical depth", hasTechnicalDepth ? (answer.length >= 140 ? "strong" : "partial") : "weak", hasTechnicalDepth ? "Concrete system details are present." : "The answer lacks implementation detail."),
    makeDimension("ownership-clarity", "Ownership clarity", hasOwnership ? "strong" : "weak", hasOwnership ? "Personal decisions and actions are visible." : "Team outcomes are not separated from personal ownership."),
    makeDimension("architecture-reasoning", "Architecture reasoning", hasReasoning ? "strong" : "partial", hasReasoning ? "The answer explains why the approach was chosen." : "The decision rationale is incomplete."),
    makeDimension("tradeoff-awareness", "Tradeoff awareness", hasTradeoff ? "strong" : "missing", hasTradeoff ? "A real alternative, cost, or downside is named." : "No tradeoff or rejected alternative is explained."),
    makeDimension("scale", "Scale", hasScale ? (unverifiedLinkedMetric ? "needs-verification" : "strong") : "missing", hasScale ? (unverifiedLinkedMetric ? "The linked metric still needs verification." : "Specific scale or measurement is present.") : "No scale, metric, or operating range is given."),
    makeDimension("impact", "Impact", hasImpact ? "strong" : "missing", hasImpact ? "The answer connects the work to an outcome." : "The result for customers, the business, or engineering is absent."),
    makeDimension("evidence", "Evidence", linkedEvidence.length > 0 ? "strong" : record.evidence.length > 0 ? "needs-verification" : "missing", linkedEvidence.length > 0 ? `${linkedEvidence.length} evidence item${linkedEvidence.length === 1 ? " is" : "s are"} linked to this answer.` : record.evidence.length > 0 ? "Evidence exists on the record but is not linked to this answer." : "No supporting evidence is attached."),
    makeDimension("follow-up-readiness", "Follow-up readiness", question.answerStatus === "practiced" && question.followUpQuestions.length >= 2 ? "interview-ready" : question.followUpQuestions.length > 0 ? "partial" : "weak", question.followUpQuestions.length > 0 ? `${question.followUpQuestions.length} follow-up prompt${question.followUpQuestions.length === 1 ? " is" : "s are"} prepared.` : "Likely follow-up questions are not prepared."),
    makeDimension("credibility", "Credibility", generic ? "weak" : unverifiedLinkedMetric ? "needs-verification" : linkedEvidence.length > 0 || linkedMetrics.some((metric) => metric.verification === "verified") ? "strong" : "partial", generic ? "Generic phrasing makes the claim difficult to defend." : unverifiedLinkedMetric ? "A supporting number is not verified." : "The answer is internally plausible; linked proof would make it stronger."),
  ];

  const strengths = dimensions.filter((dimension) => dimension.status === "strong" || dimension.status === "interview-ready").map((dimension) => `${dimension.label}: ${dimension.reason}`);
  const weaknesses = dimensions.filter((dimension) => dimension.status === "weak" || dimension.status === "needs-verification").map((dimension) => `${dimension.label}: ${dimension.reason}`);
  const missingElements = dimensions.filter((dimension) => dimension.status === "missing").map((dimension) => dimension.label);
  const points: Record<QualityStatus, number> = { missing: 0, weak: 25, partial: 55, strong: 85, "interview-ready": 100, "needs-verification": 40, "not-applicable": 100 };
  const score = Math.round(dimensions.reduce((sum, dimension) => sum + points[dimension.status], 0) / dimensions.length);
  const unresolved = dimensions.filter((dimension) => dimension.status === "missing" || dimension.status === "weak" || dimension.status === "needs-verification");

  let status: QualityStatus = "partial";
  if (explicitStatus === "needs-verification" || unverifiedLinkedMetric) status = "needs-verification";
  else if (question.answerStatus === "practiced" && unresolved.length === 0 && linkedEvidence.length > 0 && question.followUpQuestions.length >= 2) status = "interview-ready";
  else if ((question.answerStatus === "prepared" || question.answerStatus === "practiced") && unresolved.length === 0 && score >= 75) status = "strong";
  else if (unresolved.length >= 4 || generic) status = "weak";

  const firstIssue = dimensions.find((dimension) => dimension.status === "missing" || dimension.status === "weak" || dimension.status === "needs-verification");
  const improvementPrompt = firstIssue ? `Improve next: ${firstIssue.reason}` : "Practice this answer at recruiter, engineer, and principal depth.";
  const deepPersona = persona.includes("principal") || persona.includes("staff") || persona.includes("bar");
  const personaNotes = deepPersona && (missingElements.includes("Tradeoff awareness") || missingElements.includes("Evidence"))
    ? "Good recruiter answer, weak Principal Engineer answer"
    : status === "interview-ready"
      ? `Interview-ready for ${question.reviewerPersona}`
      : undefined;

  return { status, score, strengths, weaknesses, missingElements, improvementPrompt, personaNotes, dimensions };
}

/** @deprecated Kept for comparison while migrating old stored scores. */
export function evaluateQuestionQualityLegacy(question: CorpusQuestionView, record: CorpusRecord): Omit<AnswerQualityAssessment, "dimensions"> {
  const answer = question.preparedAnswer?.trim() ?? "";
  const weaknesses: string[] = [];
  const strengths: string[] = [];
  const missingElements: string[] = [];
  const persona = question.reviewerPersona.toLowerCase();

  if (!answer) {
    return {
      status: "missing",
      score: 0,
      strengths: [],
      weaknesses: ["No answer recorded"],
      missingElements: ["Direct response", "Supporting metric", "Ownership statement"],
      improvementPrompt: "Write a direct answer with ownership, one tradeoff, and one metric.",
      personaNotes: `Unanswered ${question.reviewerPersona} question — high interview risk.`,
    };
  }

  if (answer.length < 60) weaknesses.push("Answer is too brief for deep probing");
  else strengths.push("Sufficient length for explanation");

  if (isWeakText(answer)) weaknesses.push("Ownership or scope is unclear");
  if (/\d|%|x\b|\btps\b|\bms\b/i.test(answer)) strengths.push("Includes quantified detail");
  else missingElements.push("Specific metric or scale");

  if (/because|tradeoff|instead|chose|decided|alternative/i.test(answer)) strengths.push("Shows reasoning");
  else missingElements.push("Tradeoff or decision rationale");

  if (/i |my |led |owned |designed |drove /i.test(answer)) strengths.push("Clear personal ownership");
  else weaknesses.push("Ownership is unclear");

  if (record.evidence.length > 0 && answer.length > 100) strengths.push("Supported by linked evidence");
  else if (persona.includes("principal") || persona.includes("staff") || persona.includes("bar")) {
    missingElements.push("Evidence reference for deep probe");
  }

  if ((persona.includes("principal") || persona.includes("staff")) && !/tradeoff|alternative|because|instead/i.test(answer)) {
    weaknesses.push("Good surface answer, weak for Principal/Staff probing");
  }
  if (persona.includes("recruiter") && answer.length > 40 && strengths.length >= 1) {
    strengths.push("Clear enough for recruiter screen");
  }

  let status: QualityStatus = "partial";
  if (question.answerStatus === "practiced" && weaknesses.length === 0) status = "interview-ready";
  else if (question.answerStatus === "prepared" && weaknesses.length <= 1) status = "strong";
  else if (weaknesses.length >= 2) status = "weak";
  else if (question.answerStatus === "draft") status = "partial";

  const score = Math.max(0, Math.min(100, strengths.length * 18 - weaknesses.length * 12 + (status === "interview-ready" ? 20 : 0)));
  const improvementPrompt = weaknesses[0]
    ? `Improve next: ${weaknesses[0].toLowerCase()}.`
    : missingElements[0]
      ? `Add: ${missingElements[0].toLowerCase()}.`
      : "Practice explaining this at recruiter and principal depth.";

  const personaNotes = weaknesses.some((item) => item.includes("Principal") || item.includes("Staff"))
    ? "Good recruiter answer, weak Principal Engineer answer"
    : status === "interview-ready"
      ? `Interview-ready for ${question.reviewerPersona}`
      : undefined;

  return { status, score, strengths, weaknesses, missingElements, improvementPrompt, personaNotes };
}

/** Map a gap category to the editable CorpusRecord field used for inline answers. */
export function gapCategoryField(id: GapCategoryId): keyof CorpusRecord | null {
  switch (id) {
    case "problem-context": return "summary";
    case "ownership": return "ownership";
    case "technical-challenge": return "technicalChallenge";
    case "architecture": return "architectureDecision";
    case "alternatives": return "alternatives";
    case "tradeoffs": return "tradeoffs";
    case "scale": return "scaleDetails";
    case "reliability": return "reliabilityDetails";
    case "security": return "securityConsiderations";
    case "failure-handling": return "failureModes";
    case "business-impact": return "businessImpact";
    case "engineering-impact": return "engineeringImpact";
    case "leadership": return "leadership";
    case "cross-team": return "crossTeamInfluence";
    case "mentorship": return "mentorship";
    default: return null;
  }
}

export function heatmapDimensionSection(dimension: string): string {
  const map: Record<string, string> = {
    ownership: "ownership",
    architecture: "architecture",
    scale: "scale",
    impact: "business",
    leadership: "leadership",
    reliability: "reliability",
    security: "security",
    evidence: "evidence",
    "interview-readiness": "interview",
    "resume-readiness": "variants",
  };
  return map[dimension] ?? "overview";
}

function categoryValue(record: CorpusRecord, id: GapCategoryId): string {
  switch (id) {
    case "problem-context": return record.summary;
    case "ownership": return record.ownership;
    case "technical-challenge": return record.technicalChallenge;
    case "architecture": return record.architectureDecision;
    case "alternatives": return record.alternatives;
    case "tradeoffs": return record.tradeoffs;
    case "scale": return record.scaleDetails;
    case "business-impact": return record.businessImpact;
    case "engineering-impact": return record.engineeringImpact;
    case "reliability": return record.reliabilityDetails;
    case "security": return record.securityConsiderations;
    case "failure-handling": return record.failureModes;
    case "leadership": return record.leadership;
    case "cross-team": return record.crossTeamInfluence;
    case "mentorship": return record.mentorship;
    case "evidence": return record.evidence.map((e) => e.name).join(", ");
    case "metric-validation": return record.metrics.map((m) => `${m.name}: ${m.value}`).join("; ");
    case "interview-story": return record.interviewQuestions.filter((q) => q.preparedAnswer).map((q) => q.preparedAnswer).join(" ");
    case "follow-up-readiness": return record.interviewQuestions.filter((q) => q.answerStatus === "prepared" || q.answerStatus === "practiced").length.toString();
    default: return "";
  }
}

function categoryQuestion(id: GapCategoryId, record: CorpusRecord): string {
  const tech = record.technologies[0] ?? "this system";
  const questions: Record<GapCategoryId, string> = {
    "problem-context": "What problem existed before your work, and who felt the pain?",
    ownership: "What did you personally decide, build, or own versus the broader team?",
    "technical-challenge": "What made this technically hard beyond a standard implementation?",
    architecture: `Why was ${tech} (or your chosen approach) the right architecture here?`,
    alternatives: "What credible alternatives did you reject, and why?",
    tradeoffs: "What cost or complexity did you accept to get the outcome?",
    scale: "What scale did the system reach, and how was load handled?",
    "business-impact": "What business or customer outcome changed because of this work?",
    "engineering-impact": "How did engineering velocity, quality, or cost change?",
    reliability: "How did you measure and protect reliability?",
    security: "What security constraints or controls were required?",
    "failure-handling": "What failed during rollout, and what did you change?",
    leadership: "How did you influence teams beyond direct execution?",
    "cross-team": "Which teams depended on your decision, and how did you align them?",
    mentorship: "Who did you mentor or unblock, with what result?",
    evidence: "What artifact proves this claim is real?",
    "metric-validation": "Where does this metric come from, and who can verify it?",
    "interview-story": "Can you explain this accomplishment in 90 seconds at recruiter and principal depth?",
    "follow-up-readiness": "What follow-up questions are you prepared for?",
  };
  return questions[id];
}

function categoryWhy(id: GapCategoryId): string {
  const reasons: Partial<Record<GapCategoryId, string>> = {
    architecture: "Staff and principal reviewers probe architecture choices first.",
    tradeoffs: "Without tradeoffs, the story sounds like marketing copy.",
    ownership: "Recruiters and hiring managers filter for unclear ownership early.",
    "metric-validation": "Unverified metrics are a common rejection trigger.",
    evidence: "Claims without proof weaken reviewer confidence and interview defensibility.",
    "business-impact": "Impact separates senior stories from task lists.",
    scale: "Scale questions expose whether you understand production constraints.",
  };
  return reasons[id] ?? "This category affects resume credibility and interview depth.";
}

function categoryImpact(id: GapCategoryId): { resume: "high" | "medium" | "low"; interview: "high" | "medium" | "low" } {
  const high: GapCategoryId[] = ["architecture", "ownership", "metric-validation", "business-impact", "tradeoffs", "evidence"];
  const medium: GapCategoryId[] = ["technical-challenge", "scale", "failure-handling", "leadership", "reliability"];
  if (high.includes(id)) return { resume: "high", interview: "high" };
  if (medium.includes(id)) return { resume: "medium", interview: "medium" };
  return { resume: "low", interview: "low" };
}

function evaluateCategoryStatus(record: CorpusRecord, id: GapCategoryId): QualityStatus {
  const override = record.qualityStatusOverrides[id];
  if (override) return override;
  if (id === "evidence") {
    if (record.evidence.length === 0) return "missing";
    if (record.evidence.length >= 2) return "strong";
    return "partial";
  }
  if (id === "metric-validation") return evaluateMetric(record);
  if (id === "interview-story") {
    const answered = record.interviewQuestions.filter((q) => q.preparedAnswer?.trim()).length;
    if (answered === 0) return record.interviewQuestions.length === 0 ? "missing" : "weak";
    const practiced = record.interviewQuestions.filter((q) => q.answerStatus === "practiced").length;
    if (practiced >= 2) return "interview-ready";
    if (answered >= 2) return "strong";
    return "partial";
  }
  if (id === "follow-up-readiness") {
    if (record.interviewQuestions.length === 0) return "missing";
    const weak = record.interviewQuestions.filter((q) => evaluateQuestionQuality(q, record).status === "weak" || evaluateQuestionQuality(q, record).status === "missing").length;
    if (weak === 0 && record.interviewQuestions.length > 0) return "interview-ready";
    if (weak > 2) return "missing";
    return "partial";
  }
  return evaluateField(categoryValue(record, id));
}

function defaultReviewerPersona(id: GapCategoryId): string {
  if (["architecture", "alternatives", "tradeoffs", "scale"].includes(id)) return "Principal engineer";
  if (["reliability", "failure-handling"].includes(id)) return "SRE reviewer";
  if (id === "security") return "Security reviewer";
  if (["leadership", "cross-team", "mentorship"].includes(id)) return "Hiring manager";
  if (["evidence", "metric-validation"].includes(id)) return "Bar raiser";
  if (["interview-story", "follow-up-readiness"].includes(id)) return "Interview panel";
  return "Hiring manager";
}

export function buildGapMap(record: CorpusRecord): GapItem[] {
  return GAP_CATEGORIES.map((cat): GapItem => {
    const status = evaluateCategoryStatus(record, cat.id);
    const value = categoryValue(record, cat.id);
    const impact = categoryImpact(cat.id);
    const relatedConcern = record.concerns.find((c) => c.category.toLowerCase().includes(cat.label.split(" ")[0]!.toLowerCase()) || c.concern.toLowerCase().includes(cat.id.replace("-", " ")));

    let missingDetail = "";
    if (status === "missing") missingDetail = `No ${cat.label.toLowerCase()} documented.`;
    else if (status === "weak") missingDetail = `${cat.label} exists but lacks specificity.`;
    else if (status === "needs-verification") missingDetail = `${cat.label} needs a verified source.`;
    else if (status === "partial") missingDetail = `${cat.label} is started but incomplete.`;

    let suggestedAction = "Add a concise, specific answer with evidence.";
    if (status === "needs-verification") suggestedAction = "Attach a dashboard, RFC, or review that validates the claim.";
    if (status === "strong" || status === "interview-ready") suggestedAction = "Practice explaining this in a mock interview.";

    return {
      id: cat.id,
      category: cat.label,
      status,
      missingDetail,
      whyItMatters: categoryWhy(cat.id),
      question: relatedConcern ? relatedConcern.concern : categoryQuestion(cat.id, record),
      currentAnswer: value,
      suggestedAction,
      resumeImpact: impact.resume,
      interviewRisk: impact.interview,
      effort: status === "missing" ? "medium" : "low",
      relatedConcernId: relatedConcern?.id,
      reviewerPersona: relatedConcern?.reviewer ?? defaultReviewerPersona(cat.id),
    };
  }).sort((a, b) => {
    const score = (item: GapItem) => impactRank(item.resumeImpact) * 3 + impactRank(item.interviewRisk) * 2 - statusRank(item.status);
    return score(b) - score(a);
  });
}

export function summarizeBulletReadiness(record: CorpusRecord): BulletReadinessSummary {
  const gaps = buildGapMap(record);
  const countable = gaps.filter((g) => g.status !== "not-applicable");
  const missingCount = countable.filter((g) => g.status === "missing").length;
  const weakCount = countable.filter((g) => g.status === "weak").length;
  const partialCount = countable.filter((g) => g.status === "partial").length;
  const strongCount = countable.filter((g) => g.status === "strong").length;
  const interviewReadyCount = countable.filter((g) => g.status === "interview-ready").length;
  const needsVerificationCount = countable.filter((g) => g.status === "needs-verification").length;
  const notApplicableCount = gaps.length - countable.length;

  const topGapItem = gaps.find((g) => g.status === "missing" || g.status === "weak" || g.status === "needs-verification") ?? gaps[0]!;

  let overallStatus: QualityStatus = "partial";
  if (missingCount >= 3) overallStatus = "missing";
  else if (missingCount > 0 || weakCount >= 2) overallStatus = "weak";
  else if (missingCount === 0 && weakCount === 0 && partialCount === 0 && needsVerificationCount === 0 && interviewReadyCount >= 3) overallStatus = "interview-ready";
  else if (missingCount === 0 && weakCount === 0 && partialCount === 0 && needsVerificationCount === 0 && strongCount > 0) overallStatus = "strong";

  const completionPercent = countable.length === 0 ? 100 : Math.round(((strongCount + interviewReadyCount + partialCount * 0.55 + weakCount * 0.25 + needsVerificationCount * 0.25) / countable.length) * 100);

  const segments = ([
    { status: "missing", count: missingCount },
    { status: "weak", count: weakCount },
    { status: "partial", count: partialCount },
    { status: "strong", count: strongCount },
    { status: "interview-ready", count: interviewReadyCount },
    { status: "needs-verification", count: needsVerificationCount },
  ] satisfies BulletReadinessSummary["segments"]).filter((segment) => segment.count > 0);

  return {
    overallStatus,
    missingCount,
    weakCount,
    partialCount,
    strongCount,
    interviewReadyCount,
    needsVerificationCount,
    notApplicableCount,
    completionPercent,
    roastResistance: Math.round((record.roastResistance + completionPercent) / 2),
    topGap: topGapItem.category,
    topGapCategory: topGapItem.id,
    segments,
  };
}

export function dimensionStatus(record: CorpusRecord, dimension: HeatmapDimension): QualityStatus {
  switch (dimension) {
    case "ownership": return evaluateCategoryStatus(record, "ownership");
    case "architecture": return evaluateCategoryStatus(record, "architecture");
    case "scale": return evaluateCategoryStatus(record, "scale");
    case "impact": return fieldStatus(record.businessImpact || record.engineeringImpact, 50);
    case "leadership": return evaluateCategoryStatus(record, "leadership");
    case "reliability": return evaluateCategoryStatus(record, "reliability");
    case "security": return evaluateCategoryStatus(record, "security");
    case "evidence": return record.evidence.length === 0 ? "missing" : record.evidence.length >= 2 ? "strong" : "partial";
    case "interview-readiness": return summarizeBulletReadiness(record).interviewReadyCount >= 2 ? "interview-ready" : summarizeBulletReadiness(record).missingCount > 3 ? "missing" : "partial";
    case "resume-readiness": return record.readiness === "ready" ? "strong" : record.readiness === "needs-input" ? "missing" : "partial";
    default: return "partial";
  }
}

export function generateMissingQuestions(record: CorpusRecord): GeneratedQuestion[] {
  const text = [record.currentBullet, record.summary, record.architectureDecision, ...record.technologies].join(" ").toLowerCase();
  const questions: GeneratedQuestion[] = [];
  let index = 0;

  const add = (question: string, persona: string, type: string, trigger: string, category: GapCategoryId, difficulty: GeneratedQuestion["difficulty"] = "advanced") => {
    questions.push({
      id: `${record.id}-gen-${index++}`,
      question,
      reviewerPersona: persona,
      interviewType: type,
      difficulty,
      trigger,
      category,
    });
  };

  if (/step functions|workflow|state machine/i.test(text)) {
    add("Why Step Functions instead of Kafka, SQS, or a custom workflow engine?", "Principal engineer", "System design", "Step Functions", "architecture", "expert");
    add("How were retries and partial failures handled?", "Staff engineer", "Technical deep dive", "Step Functions", "failure-handling");
    add("What workflow state was persisted, and for how long?", "Senior engineer", "Technical deep dive", "Step Functions", "architecture");
    add("What concurrency limit protected downstream systems?", "SRE reviewer", "Reliability", "Step Functions", "scale");
    add("How did you prevent duplicate replay or repeated side effects?", "Staff engineer", "Reliability", "Step Functions", "failure-handling");
  }

  if (/kafka|event|stream|queue/i.test(text)) {
    add("How was ordering guaranteed across partitions or regions?", "Principal engineer", "System design", "Event streaming", "architecture", "expert");
    add("What backpressure mechanism protected downstream consumers?", "Staff engineer", "Reliability", "Event streaming", "reliability");
  }

  if (/\d+\s*(region|azure|aws|gcp)/i.test(text) || /multi-region|multiregion/i.test(text)) {
    add("How was regional isolation implemented?", "Principal engineer", "System design", "Multi-region", "architecture", "expert");
    add("How did failover work without violating data residency?", "Staff engineer", "Reliability", "Multi-region", "reliability");
    add("How was blast radius limited during regional incidents?", "SRE reviewer", "Reliability", "Multi-region", "failure-handling");
    add("How was configuration deployed consistently across regions?", "Staff engineer", "Operations", "Multi-region", "reliability");
    add("How were data residency requirements enforced?", "Security reviewer", "Security", "Multi-region", "security");
  }

  if (/\d+k?\s*tps|\d+\s*requests|\d+\s*rps|100k|1m/i.test(text)) {
    add("Was this average or peak throughput, and over what window?", "Bar raiser", "Technical deep dive", "Throughput metric", "metric-validation", "expert");
    add("What bottleneck appeared first as load increased?", "Staff engineer", "System design", "Throughput metric", "scale");
    add("What load tests validated the design before launch?", "Senior engineer", "Technical deep dive", "Throughput metric", "evidence");
    add("What latency was sustained at peak load?", "SRE reviewer", "Reliability", "Throughput metric", "scale");
    add("How was backpressure handled when consumers fell behind?", "Staff engineer", "Reliability", "Throughput metric", "reliability");
  }

  if (/rag|llm|model|ai|gpu|embedding/i.test(text)) {
    add("What part of the pipeline was deterministic versus model-generated?", "AI infrastructure reviewer", "Technical deep dive", "AI/RAG", "architecture", "expert");
    add("How were hallucinations detected and handled in production?", "Principal engineer", "Security", "AI/RAG", "security");
    add("How was output quality measured over time?", "Staff engineer", "Metrics", "AI/RAG", "metric-validation");
    add("How were compliance and data-handling constraints enforced?", "Security reviewer", "Security", "AI/RAG", "security");
    add("What deterministic fallback existed when the model was unavailable or uncertain?", "SRE reviewer", "Reliability", "AI/RAG", "failure-handling");
  }

  if (/led|mentored|influenced|aligned|cross-team|cross team|adopted by|teams? adopted/i.test(text)) {
    add("Which decisions changed because of your influence, and how did you earn alignment?", "Hiring manager", "Leadership", "Leadership claim", "cross-team");
    add("What did the team do differently after your mentorship or technical direction?", "Staff engineer", "Leadership", "Leadership claim", "mentorship");
  }

  if (/revenue|customer|conversion|cost|saved|adoption|business|launch/i.test(text)) {
    add("How was this business outcome attributed to your work rather than another change?", "Hiring manager", "Impact", "Business-impact claim", "business-impact");
  }

  if (/secure|security|privacy|compliance|auth|encryption|pii/i.test(text)) {
    add("What threat model or compliance requirement shaped the design?", "Security reviewer", "Security", "Security claim", "security");
  }

  if (/reliable|availability|slo|incident|failover|retry|resilien/i.test(text)) {
    add("Which SLO or failure budget proved the reliability claim?", "SRE reviewer", "Reliability", "Reliability claim", "reliability");
  }

  record.technologies.slice(0, 4).forEach((tech) => {
    if (questions.some((q) => q.trigger === tech)) return;
    add(`Why was ${tech} chosen over alternatives for this workload?`, "Senior engineer", "Technical deep dive", tech, "architecture", "intermediate");
  });

  record.metrics.slice(0, 2).forEach((metric) => {
    add(`How was “${metric.value}” for ${metric.name} measured and validated?`, "Hiring manager", "Behavioral", metric.name, "metric-validation", "intermediate");
  });

  if (record.concerns.length > 0) {
    record.concerns.slice(0, 3).forEach((concern) => {
      add(concern.concern.endsWith("?") ? concern.concern : `${concern.concern} — what is your answer?`, concern.reviewer, "Deep dive", "Reviewer concern", "architecture");
    });
  }

  return questions.filter((question, questionIndex) =>
    questions.findIndex((candidate) => candidate.question.toLowerCase() === question.question.toLowerCase()) === questionIndex,
  ).slice(0, 18);
}

export function buildResearchQueue(records: CorpusRecord[]): ResearchItem[] {
  const items: ResearchItem[] = [];
  records.forEach((record) => {
    record.metrics.filter((m) => m.verification !== "verified").forEach((metric, index) => {
      items.push({
        id: `${record.id}-research-metric-${index}`,
        recordId: record.id,
        recordTitle: record.title,
        missingFact: `Validate ${metric.name}: ${metric.value}`,
        whyItMatters: "Unverified metrics weaken resume and bar-raiser credibility.",
        whereToLook: "Dashboards, launch reviews, or incident analytics",
        suggestedSource: "Metrics system or reliability scorecard",
        priority: "high",
        status: "open",
      });
    });
    if (record.evidence.length === 0 && record.metrics.length > 0) {
      items.push({
        id: `${record.id}-research-evidence`,
        recordId: record.id,
        recordTitle: record.title,
        missingFact: "Locate architecture RFC or design doc",
        whyItMatters: "Evidence makes architecture and scale claims defensible.",
        whereToLook: "Internal docs, Confluence, or repo ADRs",
        suggestedSource: "Design docs",
        priority: "high",
        status: "open",
      });
    }
    buildGapMap(record)
      .filter((g) => g.status === "missing" && g.resumeImpact === "high")
      .slice(0, 2)
      .forEach((gap, index) => {
        items.push({
          id: `${record.id}-research-gap-${index}`,
          recordId: record.id,
          recordTitle: record.title,
          missingFact: gap.missingDetail,
          whyItMatters: gap.whyItMatters,
          whereToLook: "Project docs, emails, or performance reviews",
          suggestedSource: "Planning documents",
          priority: gap.interviewRisk === "high" ? "high" : "medium",
          status: "open",
        });
      });
  });
  return items.sort((a, b) => impactRank(b.priority) - impactRank(a.priority)).slice(0, 40);
}

export function rankPriorityItems(records: CorpusRecord[], limit = 5): PriorityItem[] {
  const items: PriorityItem[] = [];

  records.forEach((record) => {
    buildGapMap(record)
      .filter((g) => g.status === "missing" || g.status === "weak" || g.status === "needs-verification")
      .forEach((gap) => {
        items.push({
          id: `${record.id}-priority-${gap.id}`,
          recordId: record.id,
          recordTitle: record.title,
          type: "gap",
          title: gap.category,
          whyItMatters: gap.whyItMatters,
          reviewers: gap.reviewerPersona ? [gap.reviewerPersona] : ["Hiring manager", "Staff engineer"],
          resumeImpact: gap.resumeImpact,
          interviewRisk: gap.interviewRisk,
          benefit: gap.suggestedAction,
          likelihood: gap.interviewRisk,
          evidenceAvailability: record.evidence.length >= 2 ? "high" : record.evidence.length === 1 ? "medium" : "low",
          effort: gap.effort,
          roleRelevance: gap.resumeImpact,
          reviewerCount: gap.relatedConcernId ? 2 : 1,
          score: 0,
          gapCategory: gap.id,
        });
      });

    record.interviewQuestions
      .filter((q) => q.answerStatus === "unanswered" || evaluateQuestionQuality(q, record).status === "weak")
      .forEach((q) => {
        const quality = evaluateQuestionQuality(q, record);
        items.push({
          id: `${record.id}-priority-q-${q.id}`,
          recordId: record.id,
          recordTitle: record.title,
          type: "question",
          title: q.question,
          whyItMatters: quality.weaknesses[0] ?? "Unanswered interview risk",
          reviewers: [q.reviewerPersona],
          resumeImpact: q.difficulty === "expert" ? "high" : "medium",
          interviewRisk: "high",
          benefit: "Prepare a credible answer with metric and tradeoff",
          likelihood: q.difficulty === "expert" || q.difficulty === "advanced" ? "high" : "medium",
          evidenceAvailability: q.evidenceIds.length > 0 ? "high" : record.evidence.length > 0 ? "medium" : "low",
          effort: q.preparedAnswer?.trim() ? "low" : "medium",
          roleRelevance: q.reviewerPersona.toLowerCase().includes("principal") || q.reviewerPersona.toLowerCase().includes("staff") ? "high" : "medium",
          reviewerCount: 1,
          score: 0,
          questionId: q.id,
        });
      });

    record.concerns
      .filter((c) => c.status === "unanswered" || c.status === "investigating")
      .forEach((c) => {
        items.push({
          id: `${record.id}-priority-c-${c.id}`,
          recordId: record.id,
          recordTitle: record.title,
          type: "concern",
          title: c.concern,
          whyItMatters: `${c.reviewer} flagged this as ${c.severity} severity`,
          reviewers: [c.reviewer],
          resumeImpact: c.severity === "critical" ? "high" : "medium",
          interviewRisk: c.severity === "critical" || c.severity === "high" ? "high" : "medium",
          benefit: "Resolve before using this bullet on a target resume",
          likelihood: c.severity === "critical" || c.severity === "high" ? "high" : "medium",
          evidenceAvailability: record.evidence.length > 0 ? "medium" : "low",
          effort: "medium",
          roleRelevance: c.severity === "critical" ? "high" : "medium",
          reviewerCount: 1,
          score: 0,
        });
      });
  });

  const scored = items.map((item) => ({
    ...item,
    score:
      impactRank(item.resumeImpact) * 5
      + impactRank(item.interviewRisk) * 4
      + impactRank(item.likelihood) * 3
      + impactRank(item.roleRelevance) * 3
      + impactRank(item.evidenceAvailability) * 2
      + Math.min(item.reviewerCount, 3) * 2
      - impactRank(item.effort),
  })).sort((a, b) => b.score - a.score);

  const selected: PriorityItem[] = [];
  const perRecord = new Map<string, number>();
  for (const item of scored) {
    if (selected.length >= limit) break;
    const used = perRecord.get(item.recordId) ?? 0;
    if (used >= 2 && records.length > 1) continue;
    selected.push(item);
    perRecord.set(item.recordId, used + 1);
  }
  if (selected.length < limit) {
    for (const item of scored) {
      if (selected.length >= limit) break;
      if (!selected.some((candidate) => candidate.id === item.id)) selected.push(item);
    }
  }
  return selected;
}

export function evaluateResumeBullet(record: CorpusRecord): ResumeBulletReadiness {
  const summary = summarizeBulletReadiness(record);
  const unsupportedMetric = record.metrics.some((m) => m.verification === "unverified" && /\d/.test(m.value));
  const missingArch = evaluateField(record.architectureDecision) === "missing";
  const weakOwnership = evaluateField(record.ownership) === "weak" || evaluateField(record.ownership) === "missing";

  if (unsupportedMetric && record.metrics.some((m) => m.confidence === "low")) {
    return {
      recordId: record.id,
      label: record.title,
      indicator: "not-recommended",
      message: "Contains high-risk unverified numbers",
      blockReason: "Verify metrics before using this bullet on a competitive application.",
    };
  }
  if (missingArch) {
    return { recordId: record.id, label: record.title, indicator: "missing-architecture", message: "Missing architecture context" };
  }
  if (weakOwnership) {
    return { recordId: record.id, label: record.title, indicator: "weak-ownership", message: "Weak ownership signal" };
  }
  if (summary.missingCount >= 3) {
    return { recordId: record.id, label: record.title, indicator: "interview-risk", message: `${summary.missingCount} missing categories — interview risk` };
  }
  if (unsupportedMetric) {
    return { recordId: record.id, label: record.title, indicator: "strong-unverified", message: "Strong but metric unverified" };
  }
  if (summary.overallStatus === "interview-ready" || summary.overallStatus === "strong") {
    return { recordId: record.id, label: record.title, indicator: "ready", message: "Ready for resume" };
  }
  return { recordId: record.id, label: record.title, indicator: "interview-risk", message: "Needs more detail before targeting staff roles" };
}

export function recordMatchesQualityFilter(record: CorpusRecord, filter: string): boolean {
  const summary = summarizeBulletReadiness(record);
  const gaps = buildGapMap(record);
  switch (filter) {
    case "missing": return summary.missingCount > 0;
    case "weak": return summary.weakCount > 0;
    case "needs-verification": return summary.needsVerificationCount > 0;
    case "interview-ready": return summary.interviewReadyCount >= 2;
    case "high-interview-risk": return summary.missingCount >= 3;
    case "high-resume-impact": return gaps.some((g) => g.resumeImpact === "high" && (g.status === "missing" || g.status === "weak"));
    case "no-evidence": return record.evidence.length === 0;
    case "no-metric": return record.metrics.length === 0;
    case "no-architecture": return evaluateField(record.architectureDecision) === "missing";
    case "no-ownership": return evaluateField(record.ownership) === "missing" || evaluateField(record.ownership) === "weak";
    case "no-leadership": return !record.leadership.trim();
    case "principal-unanswered": return record.interviewQuestions.some((q) => q.reviewerPersona.toLowerCase().includes("principal") && q.answerStatus === "unanswered");
    default: return true;
  }
}

export const QUALITY_FILTER_OPTIONS = [
  { id: "missing", label: "Missing" },
  { id: "weak", label: "Needs detail" },
  { id: "needs-verification", label: "Needs verification" },
  { id: "interview-ready", label: "Interview ready" },
  { id: "high-interview-risk", label: "High interview risk" },
  { id: "high-resume-impact", label: "High resume impact" },
  { id: "no-evidence", label: "No evidence" },
  { id: "no-metric", label: "No metric" },
  { id: "no-architecture", label: "No architecture" },
  { id: "no-ownership", label: "No ownership" },
  { id: "no-leadership", label: "No leadership" },
  { id: "principal-unanswered", label: "Principal unanswered" },
] as const;

export function getFocusQueue(record: CorpusRecord): Array<GapItem | { type: "question"; question: CorpusQuestionView; gap: GapItem }> {
  const gaps = buildGapMap(record).filter((g) => g.status === "missing" || g.status === "weak" || g.status === "needs-verification");
  const unanswered = record.interviewQuestions.filter((q) => q.answerStatus === "unanswered" || evaluateQuestionQuality(q, record).status === "weak");
  const queue: Array<GapItem | { type: "question"; question: CorpusQuestionView; gap: GapItem }> = [...gaps];
  unanswered.slice(0, 5).forEach((question) => {
    const relatedGap = gaps.find((g) => g.question.includes(question.question.slice(0, 20))) ?? gaps[0];
    if (relatedGap) queue.push({ type: "question", question, gap: relatedGap });
  });
  return queue.slice(0, 12);
}

export interface MappedReviewerConcern {
  question?: string;
  whyItMatters: string;
  response?: string;
  suggestedChange?: string;
  resolutionStatus: QualityStatus;
  resumeImpact: "high" | "medium" | "low";
  relatedBullet: string;
}

export function mapReviewerConcern(record: CorpusRecord, concern: { id: string; reviewer: string; category: string; severity: string; concern: string; status: string }): MappedReviewerConcern {
  const gaps = buildGapMap(record);
  const gap = gaps.find((item) =>
    item.reviewerPersona === concern.reviewer
    || concern.category.toLowerCase().includes(item.category.toLowerCase().split(" ")[0] ?? "")
    || item.missingDetail?.toLowerCase().includes(concern.concern.slice(0, 24).toLowerCase()),
  );
  const relatedQuestion = record.interviewQuestions.find((question) =>
    question.question.toLowerCase().includes(concern.concern.split(" ").slice(0, 4).join(" ").toLowerCase())
    || concern.concern.toLowerCase().includes(question.question.split(" ").slice(0, 4).join(" ").toLowerCase()),
  );

  let resolutionStatus: QualityStatus = gap?.status ?? "missing";
  if (concern.status === "resolved") resolutionStatus = "strong";
  else if (concern.status === "answered") resolutionStatus = resolutionStatus === "missing" ? "partial" : resolutionStatus;
  else if (concern.status === "not-applicable" || concern.status === "intentionally-omitted") resolutionStatus = "not-applicable";
  else if (concern.status === "investigating" && (resolutionStatus === "strong" || resolutionStatus === "interview-ready")) resolutionStatus = "partial";

  return {
    question: relatedQuestion?.question ?? gap?.question,
    whyItMatters: gap?.whyItMatters ?? "Reviewers use this to challenge credibility, scope, or proof before extending an offer.",
    response: relatedQuestion?.preparedAnswer,
    suggestedChange: gap?.suggestedAction,
    resolutionStatus,
    resumeImpact: gap?.resumeImpact ?? (concern.severity === "critical" || concern.severity === "high" ? "high" : "medium"),
    relatedBullet: record.title,
  };
}
