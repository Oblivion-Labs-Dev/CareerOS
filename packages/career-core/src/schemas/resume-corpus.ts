import { z } from "zod";

export const corpusReadinessSchema = z.enum(["draft", "needs-input", "review", "ready"]);

export const corpusConfidenceSchema = z.enum(["low", "medium", "high"]);

export const factProvenanceSchema = z.enum(["manual", "imported", "generated", "inferred"]);

export const metricVerificationSchema = z.enum(["unverified", "needs-evidence", "verified"]);

export const corpusMetricSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  value: z.string().min(1),
  unit: z.string().optional(),
  beforeValue: z.string().optional(),
  afterValue: z.string().optional(),
  percentageChange: z.number().optional(),
  timePeriod: z.string().optional(),
  scope: z.string().optional(),
  source: z.string().optional(),
  confidence: corpusConfidenceSchema.default("medium"),
  verification: metricVerificationSchema.default("unverified"),
  provenance: factProvenanceSchema.default("manual"),
  relatedAccomplishmentIds: z.array(z.string()).default([]),
});

export const corpusEvidenceSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  type: z.string().min(1),
  url: z.string().url().or(z.literal("")),
  description: z.string().optional(),
  capturedAt: z.string().optional(),
  provenance: factProvenanceSchema.default("manual"),
  relatedAccomplishmentIds: z.array(z.string()).default([]),
});

export const reviewerConcernStatusSchema = z.enum([
  "unanswered",
  "investigating",
  "answered",
  "resolved",
  "not-applicable",
  "intentionally-omitted",
]);

export const reviewerConcernSchema = z.object({
  id: z.string(),
  reviewer: z.string().min(1),
  category: z.string().min(1),
  severity: z.enum(["low", "medium", "high", "critical"]),
  concern: z.string().min(1),
  whyItMatters: z.string().optional(),
  question: z.string().optional(),
  response: z.string().optional(),
  suggestedChange: z.string().optional(),
  evidenceIds: z.array(z.string()).default([]),
  status: reviewerConcernStatusSchema.default("unanswered"),
  relatedAccomplishmentId: z.string(),
  provenance: factProvenanceSchema.default("generated"),
});

export const interviewAnswerStatusSchema = z.enum(["unanswered", "draft", "prepared", "practiced"]);

export const interviewQuestionSchema = z.object({
  id: z.string(),
  question: z.string().min(1),
  interviewType: z.string().min(1),
  reviewerPersona: z.string().min(1),
  difficulty: z.enum(["foundation", "intermediate", "advanced", "expert"]),
  answerStatus: interviewAnswerStatusSchema.default("unanswered"),
  preparedAnswer: z.string().optional(),
  supportingMetricIds: z.array(z.string()).default([]),
  evidenceIds: z.array(z.string()).default([]),
  followUps: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(100).default(0),
  lastPracticedAt: z.string().optional(),
  relatedAccomplishmentId: z.string(),
  provenance: factProvenanceSchema.default("generated"),
});

export const resumeVariantSchema = z.object({
  id: z.string(),
  name: z.string().min(1),
  audience: z.string().optional(),
  content: z.string(),
  status: z.enum(["draft", "published", "archived"]).default("draft"),
  updatedAt: z.string().optional(),
  provenance: factProvenanceSchema.default("manual"),
});

export const careerAccomplishmentSchema = z
  .object({
    schemaVersion: z.literal(1).default(1),
    revision: z.number().int().nonnegative().default(0),
    personId: z.string().optional(),
    corpusId: z.string().optional(),
    id: z.string(),
    title: z.string().min(1),
    company: z.string().default(""),
    role: z.string().default(""),
    project: z.string().default(""),
    timePeriod: z.string().default(""),
    summary: z.string().default(""),
    currentBullet: z.string().default(""),
    technicalChallenge: z.string().default(""),
    architectureDecision: z.string().default(""),
    tradeoffs: z.string().default(""),
    failureModes: z.string().default(""),
    reliabilityDetails: z.string().default(""),
    securityConsiderations: z.string().default(""),
    scaleDetails: z.string().default(""),
    businessImpact: z.string().default(""),
    engineeringImpact: z.string().default(""),
    leadership: z.string().default(""),
    technologies: z.array(z.string()).default([]),
    domains: z.array(z.string()).default([]),
    concepts: z.array(z.string()).default([]),
    ownership: z.string().default(""),
    readiness: corpusReadinessSchema.default("draft"),
    completeness: z.number().min(0).max(100).default(0),
    roastResistance: z.number().min(0).max(100).default(0),
    metrics: z.array(corpusMetricSchema).default([]),
    evidence: z.array(corpusEvidenceSchema).default([]),
    concerns: z.array(reviewerConcernSchema).default([]),
    interviewQuestions: z.array(interviewQuestionSchema).default([]),
    resumeVariants: z.array(resumeVariantSchema).default([]),
    linkedInVersion: z.string().default(""),
    portfolioVersion: z.string().default(""),
    missingInformation: z.array(z.string()).default([]),
    nextImprovement: z.string().default(""),
    createdAt: z.string().optional(),
    updatedAt: z.string().optional(),
    provenance: factProvenanceSchema.default("manual"),
  })
  .passthrough();

export const corpusTaxonomySchema = z.object({
  profession: z.string().min(1),
  roleLevels: z.array(z.string()).default([]),
  domains: z.array(z.string()).default([]),
  skillGroups: z.array(z.string()).default([]),
  metricUnits: z.array(z.string()).default([]),
  reviewerPersonas: z.array(z.string()).default([]),
});

export type CorpusReadiness = z.infer<typeof corpusReadinessSchema>;
export type CorpusConfidence = z.infer<typeof corpusConfidenceSchema>;
export type FactProvenance = z.infer<typeof factProvenanceSchema>;
export type MetricVerification = z.infer<typeof metricVerificationSchema>;
export type CorpusMetric = z.infer<typeof corpusMetricSchema>;
export type CorpusEvidence = z.infer<typeof corpusEvidenceSchema>;
export type ReviewerConcernStatus = z.infer<typeof reviewerConcernStatusSchema>;
export type ReviewerConcern = z.infer<typeof reviewerConcernSchema>;
export type InterviewAnswerStatus = z.infer<typeof interviewAnswerStatusSchema>;
export type InterviewQuestion = z.infer<typeof interviewQuestionSchema>;
export type ResumeVariant = z.infer<typeof resumeVariantSchema>;
export type CareerAccomplishment = z.infer<typeof careerAccomplishmentSchema>;
export type CorpusTaxonomy = z.infer<typeof corpusTaxonomySchema>;
