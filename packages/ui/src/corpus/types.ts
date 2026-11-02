import type { CorpusReadiness } from "@career-os/core";

export type { CorpusReadiness };

export type ConcernSeverity = "low" | "medium" | "high" | "critical";

export type ConcernStatus =
  | "unanswered"
  | "investigating"
  | "answered"
  | "resolved"
  | "not-applicable"
  | "intentionally-omitted";

export type InterviewAnswerStatus = "unanswered" | "draft" | "prepared" | "practiced";

export type SkillDepth = "exposure" | "working" | "production" | "deep" | "leadership";

export interface ConcernCardData {
  id: string;
  reviewer: string;
  category: string;
  severity: ConcernSeverity;
  concern: string;
  whyItMatters?: string;
  question?: string;
  response?: string;
  suggestedChange?: string;
  status: ConcernStatus;
  recordTitle?: string;
}

export interface InterviewQuestionData {
  id: string;
  question: string;
  interviewType: string;
  reviewerPersona: string;
  difficulty: "foundation" | "intermediate" | "advanced" | "expert";
  answerStatus: InterviewAnswerStatus;
  preparedAnswer?: string;
  confidence: number;
  lastPracticedAt?: string;
  recordTitle?: string;
  supportingMetric?: string;
}

export interface EvidenceItem {
  id: string;
  name: string;
  type: string;
  url: string;
  description?: string;
  recordTitle?: string;
}

export interface SkillDepthData {
  name: string;
  depth: SkillDepth;
  yearsUsed?: number;
  lastUsed?: string;
  evidenceCount: number;
  accomplishmentCount: number;
  interviewConfidence?: number;
  group?: string;
}
