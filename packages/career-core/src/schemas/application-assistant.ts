import { z } from "zod";

export const answerClassificationSchema = z.enum([
  "verified",
  "inferred",
  "unknown",
  "conflict",
  "manual_only",
]);

export const applicationAssistantStatusSchema = z.enum([
  "ready_to_prepare",
  "in_progress",
  "needs_review",
  "blocked",
  "ready_for_final_review",
  "submitted_manually",
  "archived",
]);

export const providerTypeSchema = z.enum([
  "greenhouse",
  "workday",
  "lever",
  "unknown",
  "unsupported",
]);

export const discoveryRunStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "failed",
  "cancelled",
]);

export const applicationFieldSchema = z.object({
  id: z.string().optional(),
  label: z.string(),
  normalizedKey: z.string(),
  fieldType: z.string(),
  required: z.boolean().default(false),
  options: z.array(z.string()).default([]),
  helpText: z.string().default(""),
  section: z.string().default(""),
  classification: answerClassificationSchema.default("unknown"),
  confidence: z.number().default(0),
  source: z.string().default(""),
  proposedValue: z.unknown().optional(),
  websiteValue: z.unknown().optional(),
  filled: z.boolean().default(false),
  differsFromSaved: z.boolean().default(false),
  sensitivityCategory: z.string().default("none"),
  updatedAt: z.string().optional(),
});

export const applicationDraftSchema = z.object({
  id: z.string(),
  jobId: z.string(),
  jobUrl: z.string(),
  companyName: z.string(),
  roleTitle: z.string(),
  provider: providerTypeSchema.default("unknown"),
  status: applicationAssistantStatusSchema.default("ready_to_prepare"),
  currentPage: z.string().default(""),
  currentSection: z.string().default(""),
  progress: z.number().default(0),
  resumeId: z.string().default(""),
  matchScore: z.number().default(0),
  fields: z.array(applicationFieldSchema).default([]),
  verifiedCount: z.number().default(0),
  reviewCount: z.number().default(0),
  missingCount: z.number().default(0),
  conflictingCount: z.number().default(0),
  screenshots: z.array(z.string()).default([]),
  errors: z.array(z.record(z.unknown())).default([]),
  createdAt: z.string(),
  updatedAt: z.string(),
  lastResumedAt: z.string().optional(),
});

export const discoveredJobSchema = z.object({
  id: z.string(),
  sourceProvider: providerTypeSchema,
  company: z.string(),
  title: z.string(),
  description: z.string().default(""),
  location: z.string().default(""),
  workplaceType: z.string().default(""),
  applicationUrl: z.string(),
  listingUrl: z.string(),
  externalJobId: z.string().default(""),
  salaryMin: z.number().nullable().optional(),
  salaryMax: z.number().nullable().optional(),
  currency: z.string().default(""),
  active: z.boolean().default(true),
  discoveryRunId: z.string().default(""),
  dateDiscovered: z.string(),
  match: z
    .object({
      overallScore: z.number(),
      explanation: z.string(),
      strongMatches: z.array(z.string()),
      missingQualifications: z.array(z.string()),
    })
    .optional(),
});

export const discoveryRunSchema = z.object({
  id: z.string(),
  careersUrl: z.string(),
  status: discoveryRunStatusSchema,
  provider: providerTypeSchema.default("unknown"),
  jobsFound: z.number().default(0),
  logs: z.array(z.record(z.unknown())).default([]),
  error: z.record(z.unknown()).nullable().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
  completedAt: z.string().nullable().optional(),
});

export const answerLibraryEntrySchema = z.object({
  id: z.string(),
  normalizedKey: z.string(),
  questionVariants: z.array(z.string()).default([]),
  answerType: z.string().default("short_text"),
  value: z.unknown().optional(),
  sensitivityCategory: z.string().default("none"),
  verificationStatus: z.enum(["verified", "draft", "disabled"]).default("verified"),
  source: z.string().default("user"),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type AnswerClassification = z.infer<typeof answerClassificationSchema>;
export type ApplicationAssistantStatus = z.infer<typeof applicationAssistantStatusSchema>;
export type ApplicationField = z.infer<typeof applicationFieldSchema>;
export type ApplicationDraft = z.infer<typeof applicationDraftSchema>;
export type DiscoveredJob = z.infer<typeof discoveredJobSchema>;
export type DiscoveryRun = z.infer<typeof discoveryRunSchema>;
export type AnswerLibraryEntry = z.infer<typeof answerLibraryEntrySchema>;
