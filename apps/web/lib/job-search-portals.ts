export type PortalQuality = 5 | 4 | 3;
export type WorthUsing = "yes" | "sometimes" | "excellent" | "good";

export interface JobPortal {
  name: string;
  href: string;
  bestFor: string;
  quality: PortalQuality;
  priority?: "high" | "medium" | "low";
  note?: string;
}

export interface AiMatchingPlatform {
  name: string;
  href: string;
  bestFor: string;
  aiMatching: PortalQuality;
  worthUsing: WorthUsing;
  note?: string;
}

export interface AiPlatformDetail {
  name: string;
  href: string;
  quality: PortalQuality;
  summary: string;
  features: string[];
  greatFor?: string[];
  note?: string;
}

export interface CareerAgentPlatform {
  name: string;
  href: string;
  summary: string;
  features: string[];
  note?: string;
}

export interface RecommendedStackItem {
  tool: string;
  href?: string;
  role: string;
}

export interface CompanyCareerPage {
  name: string;
  href: string;
}

export const PRIMARY_JOB_PORTALS: JobPortal[] = [
  {
    name: "LinkedIn Jobs",
    href: "https://www.linkedin.com/jobs",
    bestFor: "Overall best, recruiter outreach, networking",
    quality: 5,
    priority: "high",
    note: "Prioritize for Big Tech — aim for ~70% of applications.",
  },
  {
    name: "Wellfound",
    href: "https://wellfound.com/jobs",
    bestFor: "Startups, AI companies, equity-heavy roles",
    quality: 5,
    priority: "high",
  },
  {
    name: "Levels.fyi Jobs",
    href: "https://www.levels.fyi/jobs",
    bestFor: "Big Tech, verified compensation",
    quality: 5,
    priority: "high",
  },
  {
    name: "Otta",
    href: "https://otta.com",
    bestFor: "Curated tech companies and startups",
    quality: 4,
  },
  {
    name: "Hired",
    href: "https://hired.com",
    bestFor: "Companies apply to you",
    quality: 4,
  },
  {
    name: "Indeed",
    href: "https://www.indeed.com",
    bestFor: "Largest job database",
    quality: 4,
  },
  {
    name: "Dice",
    href: "https://www.dice.com",
    bestFor: "Enterprise software, cloud, consulting",
    quality: 4,
  },
  {
    name: "Built In",
    href: "https://builtin.com/jobs",
    bestFor: "Tech startups and mid-sized companies",
    quality: 4,
    priority: "medium",
  },
  {
    name: "Y Combinator Jobs",
    href: "https://www.ycombinator.com/jobs",
    bestFor: "YC startups",
    quality: 4,
  },
  {
    name: "GitHub Careers",
    href: "https://github.com/careers",
    bestFor: "Open source and developer-focused companies",
    quality: 3,
    note: "Also check individual company hiring pages on GitHub.",
  },
];

export const AI_JOB_PORTALS: JobPortal[] = [
  {
    name: "AI Jobs",
    href: "https://aijobs.net",
    bestFor: "AI infrastructure, agent systems, LLM engineering",
    quality: 4,
  },
  {
    name: "Hugging Face Jobs",
    href: "https://huggingface.co/jobs",
    bestFor: "ML platform and open-source AI roles",
    quality: 4,
  },
  {
    name: "OpenAI Careers",
    href: "https://openai.com/careers",
    bestFor: "Frontier AI research and product engineering",
    quality: 5,
  },
  {
    name: "Anthropic Careers",
    href: "https://www.anthropic.com/careers",
    bestFor: "AI safety and large-model engineering",
    quality: 5,
  },
];

export const BIG_TECH_CAREER_PAGES: CompanyCareerPage[] = [
  { name: "Google", href: "https://careers.google.com" },
  { name: "Meta", href: "https://www.metacareers.com" },
  { name: "Microsoft", href: "https://careers.microsoft.com" },
  { name: "Amazon", href: "https://www.amazon.jobs" },
  { name: "Stripe", href: "https://stripe.com/jobs" },
  { name: "Databricks", href: "https://www.databricks.com/company/careers" },
  { name: "Anthropic", href: "https://www.anthropic.com/careers" },
  { name: "Coinbase", href: "https://www.coinbase.com/careers" },
  { name: "Uber", href: "https://www.uber.com/us/en/careers" },
  { name: "Airbnb", href: "https://careers.airbnb.com" },
  { name: "NVIDIA", href: "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite" },
  { name: "Netflix", href: "https://jobs.netflix.com" },
];

export const USE_SPARINGLY: JobPortal[] = [
  {
    name: "Monster",
    href: "https://www.monster.com",
    bestFor: "General volume search",
    quality: 3,
    priority: "low",
    note: "Weaker for senior Big Tech roles.",
  },
  {
    name: "CareerBuilder",
    href: "https://www.careerbuilder.com",
    bestFor: "General volume search",
    quality: 3,
    priority: "low",
  },
  {
    name: "ZipRecruiter",
    href: "https://www.ziprecruiter.com",
    bestFor: "High application volume",
    quality: 3,
    priority: "low",
    note: "Good for volume, weaker for senior Big Tech roles.",
  },
];

export const BIG_TECH_PRIORITY_ORDER = [
  "LinkedIn Jobs",
  "Levels.fyi Jobs",
  "Company career pages",
  "Wellfound",
  "Built In",
];

export const BEYOND_PORTALS = [
  "Employee referrals",
  "Recruiter outreach on LinkedIn",
  "Previous coworkers",
  "Hiring managers discovering your GitHub or portfolio",
];

export const AI_MATCHING_PLATFORMS: AiMatchingPlatform[] = [
  {
    name: "ZeekData",
    href: "https://www.zeekdata.com",
    bestFor: "Finding recruiter emails + company intelligence",
    aiMatching: 5,
    worthUsing: "yes",
  },
  {
    name: "Jobright AI",
    href: "https://jobright.ai",
    bestFor: "Personalized job recommendations",
    aiMatching: 5,
    worthUsing: "yes",
  },
  {
    name: "Teal HQ",
    href: "https://www.tealhq.com",
    bestFor: "Job tracking + resume optimization",
    aiMatching: 5,
    worthUsing: "yes",
  },
  {
    name: "Final Round AI",
    href: "https://www.finalroundai.com",
    bestFor: "Resume + interview prep",
    aiMatching: 4,
    worthUsing: "yes",
  },
  {
    name: "LazyApply",
    href: "https://lazyapply.com",
    bestFor: "Automated applications",
    aiMatching: 3,
    worthUsing: "sometimes",
    note: "Use selectively for senior roles.",
  },
  {
    name: "Simplify Jobs",
    href: "https://simplify.jobs",
    bestFor: "Autofill + recommendations",
    aiMatching: 5,
    worthUsing: "excellent",
  },
  {
    name: "EarnBetter",
    href: "https://earnbetter.com",
    bestFor: "AI resume rewriting + matching",
    aiMatching: 4,
    worthUsing: "good",
  },
  {
    name: "Huntr",
    href: "https://huntr.co",
    bestFor: "Job tracker + AI assistance",
    aiMatching: 4,
    worthUsing: "good",
  },
];

export const BIG_TECH_AI_PLATFORMS: AiPlatformDetail[] = [
  {
    name: "Simplify Jobs",
    href: "https://simplify.jobs",
    quality: 5,
    summary: "Most popular among software engineers — Chrome autofill, resume tailoring, and match scores.",
    features: [
      "Chrome autofill",
      "Resume tailoring",
      "AI match score",
      "Internship to Staff-level jobs",
      "Application status tracking",
    ],
    greatFor: ["Google", "Meta", "Microsoft", "Databricks", "Stripe", "Airbnb"],
  },
  {
    name: "Jobright AI",
    href: "https://jobright.ai",
    quality: 5,
    summary: "Strong AI matching engine that recommends jobs from resume, skills, experience, and career progression.",
    features: [
      "Resume-aware recommendations",
      "Skills and experience analysis",
      "Career progression matching",
      "Beyond keyword search",
    ],
  },
  {
    name: "Teal HQ",
    href: "https://www.tealhq.com",
    quality: 5,
    summary: "Primary dashboard for many experienced engineers — organization plus AI-assisted matching.",
    features: [
      "Multiple resume versions",
      "Job tracker",
      "Match scores",
      "Missing skills analysis",
      "AI suggestions",
    ],
  },
  {
    name: "ZeekData",
    href: "https://www.zeekdata.com",
    quality: 5,
    summary: "Recruiter intelligence and outreach — ideal when referrals and direct networking beat cold applications.",
    features: [
      "Recruiter emails",
      "Hiring manager contacts",
      "Company intelligence",
      "Outreach-focused workflow",
    ],
    note: "Pairs well with CareerOS email outreach.",
  },
];

export const CAREER_AGENT_PLATFORMS: CareerAgentPlatform[] = [
  {
    name: "Sonara AI",
    href: "https://sonara.ai",
    summary: "Career agent that finds jobs, applies automatically, and tracks responses.",
    features: ["Finds jobs", "Applies automatically", "Tracks responses"],
    note: "Useful for volume; be selective with automation for senior roles.",
  },
  {
    name: "LoopCV",
    href: "https://loopcv.pro",
    summary: "Continuous search and auto-apply with daily matches.",
    features: ["Continuous job search", "Automatic applications", "Daily match emails"],
    note: "Better for broad searches than targeted Big Tech.",
  },
  {
    name: "Massive",
    href: "https://massive.careers",
    summary: "AI career coaching with job matching and recruiter introductions.",
    features: ["AI career coaching", "Job matching", "Recruiter introductions"],
    note: "Smaller than LinkedIn but growing.",
  },
];

export const RECOMMENDED_SENIOR_STACK: RecommendedStackItem[] = [
  { tool: "Simplify Jobs", href: "https://simplify.jobs", role: "Autofill + job discovery" },
  { tool: "Teal HQ", href: "https://www.tealhq.com", role: "Application tracking" },
  { tool: "ZeekData", href: "https://www.zeekdata.com", role: "Recruiter outreach" },
  { tool: "LinkedIn Premium", href: "https://www.linkedin.com/premium", role: "Recruiter visibility + networking" },
  { tool: "Levels.fyi Jobs", href: "https://www.levels.fyi/jobs", role: "Compensation + quality roles" },
  { tool: "Direct company applications", role: "Target company career pages" },
];

export const CAREEROS_AGENT_VISION = {
  headline: "Beyond keyword matching — a personal job-search agent",
  intro:
    "Most AI job platforms stop at keyword matching, resume tailoring, or automated applications. CareerOS can go further by connecting search, outreach, tracking, and learning in one system.",
  capabilities: [
    "Learn which recruiters respond to you",
    "Rank jobs based on your actual interview success",
    "Remember why previous applications failed",
    "Suggest people in your network for referrals",
    "Detect team-specific signals from public data",
    "Generate outreach tailored to the hiring manager",
    "Keep resume and portfolio aligned with each role",
  ],
  careerOsToday: [
    { label: "ApplyPilot", href: "/apply-pilot", description: "Chrome autofill + application capture" },
    { label: "Email Outreach", href: "/apply/outreach", description: "Recruiter campaigns with delivery tracking" },
    { label: "Application Tracker", href: "/applications", description: "Pipeline, submissions, and follow-ups" },
    { label: "Referrals", href: "/referrals", description: "Warm paths at target companies" },
  ],
};

export function worthUsingLabel(value: WorthUsing): string {
  if (value === "yes") return "Yes";
  if (value === "sometimes") return "Sometimes";
  if (value === "excellent") return "Excellent";
  return "Good";
}

export function qualityStars(quality: PortalQuality): string {
  const filled = "★".repeat(quality);
  const empty = "☆".repeat(5 - quality);
  return filled + empty;
}
