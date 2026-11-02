export type ToolRating = 5 | 4 | 3;
export type FreeTier = "limited" | "good";
export type WorthIt = "yes" | "ok";

export interface ResumeCheckerTool {
  name: string;
  href: string;
  atsCheck: ToolRating;
  aiFeedback: ToolRating;
  freeTier: FreeTier;
  worthIt: WorthIt;
}

export interface ResumeToolDetail {
  name: string;
  href: string;
  summary: string;
  bestFor: string[];
  catches?: string[];
  workflow?: string[];
  note?: string;
}

export interface AiReviewer {
  name: string;
  href: string;
  strengths: string[];
  promptExample?: string;
}

export const ATS_SCORE_DISCLAIMER =
  "Most ATS scanners aren't testing against a real ATS — they score using their own heuristics. The number itself is often meaningless. What matters is actionable feedback.";

export const RESUME_CHECKER_TOOLS: ResumeCheckerTool[] = [
  {
    name: "Resume Worded",
    href: "https://resumeworded.com",
    atsCheck: 4,
    aiFeedback: 5,
    freeTier: "limited",
    worthIt: "yes",
  },
  {
    name: "Jobscan",
    href: "https://www.jobscan.co",
    atsCheck: 5,
    aiFeedback: 4,
    freeTier: "limited",
    worthIt: "yes",
  },
  {
    name: "Teal HQ Resume Checker",
    href: "https://www.tealhq.com/resume-checker",
    atsCheck: 4,
    aiFeedback: 4,
    freeTier: "good",
    worthIt: "yes",
  },
  {
    name: "Enhancv Resume Checker",
    href: "https://enhancv.com/resume-checker",
    atsCheck: 4,
    aiFeedback: 4,
    freeTier: "good",
    worthIt: "yes",
  },
  {
    name: "Resume.io Resume Checker",
    href: "https://resume.io/resume-checker",
    atsCheck: 3,
    aiFeedback: 3,
    freeTier: "good",
    worthIt: "ok",
  },
  {
    name: "Kickresume AI Checker",
    href: "https://www.kickresume.com",
    atsCheck: 4,
    aiFeedback: 4,
    freeTier: "limited",
    worthIt: "ok",
  },
];

export const TOP_RESUME_TOOLS: ResumeToolDetail[] = [
  {
    name: "Resume Worded",
    href: "https://resumeworded.com",
    summary: "One of the better free tools for experienced engineers — focuses on bullet quality over keyword stuffing.",
    bestFor: ["Bullet quality", "Strong action verbs", "Quantifying impact", "Recruiter readability"],
    catches: ["Weak wording", "Vague accomplishments", "Missing metrics", "Passive language"],
  },
  {
    name: "Jobscan",
    href: "https://www.jobscan.co",
    summary: "Closest to real ATS optimization — upload your resume and the job description for a targeted match analysis.",
    bestFor: ["Missing keywords", "Hard skills gaps", "Formatting issues", "ATS compatibility", "Match percentage"],
    workflow: ["Upload resume", "Paste job description", "Review gaps — aim for 70–80%, not 100%"],
    note: "Don't obsess over 100% match. Missing non-core keywords are fine.",
  },
  {
    name: "Teal HQ",
    href: "https://www.tealhq.com/resume-checker",
    summary: "Less keyword stuffing, more holistic resume quality — strong overall workflow.",
    bestFor: ["Missing skills", "Formatting", "Readability", "Tailoring per role"],
    note: "The workflow matters more than the ATS score.",
  },
];

export const AI_REVIEWERS: AiReviewer[] = [
  {
    name: "Claude",
    href: "https://claude.ai",
    strengths: ["Clarity", "Storytelling", "Removing fluff", "Improving bullets"],
  },
  {
    name: "ChatGPT",
    href: "https://chatgpt.com",
    strengths: ["Structured rewrites", "Role-specific review", "Brutally honest feedback"],
    promptExample:
      'Review this resume as if you\'re a Senior Staff Engineer at Google. Be brutally honest. Ignore ATS scores. Focus on impact, technical depth, clarity, and interview likelihood. Rewrite weak bullets and explain why.',
  },
  {
    name: "Google Gemini",
    href: "https://gemini.google.com",
    strengths: ["Compare resume vs job description", "Missing technologies", "Qualification gaps"],
  },
];

export const RECRUITER_ACTUALLY_CARES = {
  atsFilters: ["Job titles", "Skills", "Years of experience", "Education", "Location", "Keywords"],
  humanReview: ["Impact", "Technical depth", "Ownership", "Scale", "Measurable results"],
  insight:
    'Most ATS systems parse and filter — they don\'t assign an "ATS score." Once you pass parsing, a recruiter evaluates impact and depth. A perfect scanner score won\'t fix weak bullets.',
};

export const SENIOR_RESUME_PRIORITIES = [
  "Make impact immediately obvious in the first line of each bullet",
  "Emphasize technical ownership and system scale",
  "Quantify outcomes — latency, cost, users, revenue, team size",
  'Remove generic engineering phrases ("responsible for", "worked on")',
  "Tailor each resume to the role — don't chase a generic 100% ATS match",
];

export const TARGET_COMPANIES_TAILORING = [
  "Google",
  "Databricks",
  "Stripe",
  "Anthropic",
  "Airbnb",
  "Microsoft",
  "Meta",
];

export function ratingStars(rating: ToolRating): string {
  return "★".repeat(rating) + "☆".repeat(5 - rating);
}

export function freeTierLabel(tier: FreeTier): string {
  return tier === "good" ? "Good" : "Limited";
}

export function worthItLabel(value: WorthIt): string {
  return value === "yes" ? "Yes" : "OK";
}
