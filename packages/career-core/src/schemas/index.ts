import { z } from "zod";

export const fileAttachmentSchema = z.object({
  name: z.string(),
  type: z.string(),
  base64: z.string(),
});

export const workExperienceEntrySchema = z.object({
  jobTitle: z.string(),
  company: z.string(),
  location: z.string(),
  currentlyEmployed: z.boolean(),
  startDate: z.string(),
  endDate: z.string().optional(),
  description: z.string(),
});

export const screeningAnswerSchema = z.object({
  id: z.string(),
  question: z.string(),
  answer: z.string(),
  matchPatterns: z.array(z.string()).optional(),
});

export const userProfileSchema = z.object({
  id: z.string().optional(),
  firstName: z.string(),
  lastName: z.string(),
  fullName: z.string(),
  email: z.string().email().or(z.literal("")),
  phone: z.string(),
  location: z.string(),
  linkedin: z.string(),
  github: z.string(),
  portfolio: z.string(),
  workAuthorization: z.string(),
  sponsorship: z.string(),
  yearsExperience: z.string(),
  currentTitle: z.string(),
  targetRole: z.string(),
  salaryExpectations: z.string(),
  currentCompany: z.string().optional(),
  pronouns: z.string().optional(),
  gender: z.string().optional(),
  raceEthnicity: z.string().optional(),
  hispanic: z.string().optional(),
  veteran: z.string().optional(),
  disability: z.string().optional(),
  smsConsent: z.string().optional(),
  customFields: z.record(z.string()).optional(),
  workExperience: z.array(workExperienceEntrySchema).optional(),
  screeningAnswers: z.array(screeningAnswerSchema).optional(),
});

export const resumeSchema = z.object({
  id: z.string(),
  userId: z.string().optional(),
  name: z.string(),
  mimeType: z.string(),
  base64: z.string().optional(),
  storagePath: z.string().optional(),
  parsedText: z.string().optional(),
  isDefault: z.boolean().default(false),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export const companySchema = z.object({
  id: z.string(),
  name: z.string(),
  website: z.string().optional(),
  industry: z.string().optional(),
  size: z.string().optional(),
  notes: z.string().optional(),
});

export const jobSchema = z.object({
  id: z.string(),
  companyId: z.string().optional(),
  companyName: z.string(),
  title: z.string(),
  location: z.string().optional(),
  description: z.string().optional(),
  url: z.string(),
  platform: z.string().optional(),
  salaryRange: z.string().optional(),
  remote: z.boolean().optional(),
  extractedAt: z.string().optional(),
  savedAt: z.string().optional(),
});

export const applicationStatusSchema = z.enum([
  "saved",
  "viewed",
  "parsed",
  "autofilled",
  "ready_to_submit",
  "submitted",
  "rejected",
  "interview",
  "interviewing",
  "offer",
  "withdrawn",
]);

export const applicationSchema = z.object({
  id: z.string(),
  jobId: z.string().optional(),
  companyId: z.string().optional(),
  companyName: z.string(),
  roleTitle: z.string(),
  status: applicationStatusSchema,
  priority: z.enum(["low", "medium", "high"]).default("medium"),
  url: z.string().optional(),
  resumeUsedId: z.string().optional(),
  coverLetterUsedId: z.string().optional(),
  notes: z.string().optional(),
  appliedAt: z.string().optional(),
  updatedAt: z.string(),
});

export const recruiterSchema = z.object({
  id: z.string(),
  name: z.string(),
  email: z.string().optional(),
  companyId: z.string().optional(),
  linkedin: z.string().optional(),
  notes: z.string().optional(),
  lastContactAt: z.string().optional(),
});

export const autofillFieldMappingSchema = z.object({
  id: z.string(),
  canonicalKey: z.string(),
  labelPattern: z.string(),
  selectorHint: z.string().optional(),
  platform: z.string().optional(),
  valueSource: z.string().optional(),
  confidence: z.number().min(0).max(1).optional(),
  usageCount: z.number().default(0),
  lastUsedAt: z.string().optional(),
});

export const applicationQuestionSchema = z.object({
  id: z.string(),
  applicationId: z.string().optional(),
  question: z.string(),
  answer: z.string().optional(),
  source: z.enum(["learned", "generated", "manual"]).default("manual"),
  createdAt: z.string(),
});

export const coverLetterSchema = z.object({
  id: z.string(),
  jobId: z.string().optional(),
  applicationId: z.string().optional(),
  title: z.string(),
  content: z.string(),
  tone: z.string().optional(),
  createdAt: z.string(),
});

export const interviewSchema = z.object({
  id: z.string(),
  applicationId: z.string().optional(),
  type: z.enum(["phone", "video", "onsite", "technical", "behavioral", "other"]),
  scheduledAt: z.string().optional(),
  durationMinutes: z.number().optional(),
  notes: z.string().optional(),
  outcome: z.string().optional(),
});

export const referralSchema = z.object({
  id: z.string(),
  contactName: z.string(),
  email: z.string().optional(),
  linkedin: z.string().optional(),
  companyName: z.string().optional(),
  roleTitle: z.string().optional(),
  phone: z.string().optional(),
  companyId: z.string().optional(),
  relationship: z.string().optional(),
  status: z.enum(["active", "asked", "referred", "inactive"]).optional(),
  notes: z.string().optional(),
  createdAt: z.string().optional(),
  updatedAt: z.string().optional(),
});

export const careerEventSchema = z.object({
  id: z.string(),
  type: z.string(),
  module: z.string().optional(),
  message: z.string(),
  metadata: z.record(z.unknown()).optional(),
  createdAt: z.string(),
});

export const skillSchema = z.object({
  id: z.string(),
  name: z.string(),
  level: z.enum(["beginner", "intermediate", "advanced", "expert"]).optional(),
  years: z.number().optional(),
});

export const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().optional(),
  url: z.string().optional(),
  technologies: z.array(z.string()).optional(),
});

export const educationSchema = z.object({
  id: z.string(),
  institution: z.string(),
  degree: z.string(),
  field: z.string().optional(),
  startDate: z.string().optional(),
  endDate: z.string().optional(),
});

export const experienceSchema = z.object({
  id: z.string(),
  title: z.string(),
  company: z.string(),
  location: z.string().optional(),
  startDate: z.string(),
  endDate: z.string().optional(),
  description: z.string().optional(),
  highlights: z.array(z.string()).optional(),
});

export type FileAttachment = z.infer<typeof fileAttachmentSchema>;
export type WorkExperienceEntry = z.infer<typeof workExperienceEntrySchema>;
export type ScreeningAnswer = z.infer<typeof screeningAnswerSchema>;
export type UserProfile = z.infer<typeof userProfileSchema>;
export type Resume = z.infer<typeof resumeSchema>;
export type Company = z.infer<typeof companySchema>;
export type Job = z.infer<typeof jobSchema>;
export type ApplicationStatus = z.infer<typeof applicationStatusSchema>;
export type Application = z.infer<typeof applicationSchema>;
export type Recruiter = z.infer<typeof recruiterSchema>;
export type AutofillFieldMapping = z.infer<typeof autofillFieldMappingSchema>;
export type ApplicationQuestion = z.infer<typeof applicationQuestionSchema>;
export type CoverLetter = z.infer<typeof coverLetterSchema>;
export type Interview = z.infer<typeof interviewSchema>;
export type Referral = z.infer<typeof referralSchema>;
export type CareerEvent = z.infer<typeof careerEventSchema>;
export type Skill = z.infer<typeof skillSchema>;
export type Project = z.infer<typeof projectSchema>;
export type Education = z.infer<typeof educationSchema>;
export type Experience = z.infer<typeof experienceSchema>;

export const DEFAULT_API_BASE = "http://localhost:8000";
