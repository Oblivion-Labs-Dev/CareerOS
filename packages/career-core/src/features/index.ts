import type { FeaturePriority, FeatureStatus } from "../roadmap/index.js";

export type ProductFeatureId =
  | "applypilot"
  | "profile-os"
  | "resume-intelligence"
  | "cover-letter-intelligence"
  | "job-discovery"
  | "application-intelligence"
  | "recruiter-crm"
  | "interview-os"
  | "career-analytics"
  | "career-coach"
  | "networking"
  | "portfolio-builder";

export interface ProductFeature {
  id: ProductFeatureId;
  title: string;
  description: string;
  status: FeatureStatus;
  priority: FeaturePriority;
  module: string;
  highlights: string[];
  installable: boolean;
}

export const PRODUCT_FEATURES: ProductFeature[] = [
  {
    id: "applypilot",
    title: "ApplyPilot",
    description:
      "Browser extension for job application autofill, resume attach, cover letters, unknown-field learning, and application tracking.",
    status: "in-progress",
    priority: "P0",
    module: "Application Intelligence / ApplyPilot",
    highlights: [
      "Detect & fill ATS forms",
      "Attach resume automatically",
      "Learn unknown screening questions",
      "Sync with CareerOS backend",
    ],
    installable: true,
  },
  {
    id: "profile-os",
    title: "Profile OS",
    description: "One canonical profile for contact info, work authorization, and screening defaults.",
    status: "in-progress",
    priority: "P0",
    module: "Profile OS",
    highlights: ["Shared across extension & dashboard", "Custom field support", "Screening answer bank"],
    installable: false,
  },
  {
    id: "resume-intelligence",
    title: "Resume Intelligence",
    description: "Store resumes, parse PDF text, and hydrate profile and work experience.",
    status: "in-progress",
    priority: "P0",
    module: "Resume Intelligence",
    highlights: ["PDF parsing", "Default resume selection", "Profile auto-fill"],
    installable: false,
  },
  {
    id: "job-discovery",
    title: "Job Discovery",
    description: "Extract job title, company, location, and description from application pages.",
    status: "in-progress",
    priority: "P0",
    module: "Job Discovery",
    highlights: ["Page scan heuristics", "Save job postings", "Platform detection"],
    installable: false,
  },
  {
    id: "application-intelligence",
    title: "Application Tracker",
    description: "Pipeline board, statuses, and application detail from saved to submitted.",
    status: "planned",
    priority: "P1",
    module: "Application Intelligence / ApplyPilot",
    highlights: ["Status pipeline", "Notes & priorities", "Application analytics"],
    installable: false,
  },
  {
    id: "cover-letter-intelligence",
    title: "Cover Letter Intelligence",
    description: "Generate tailored cover letters from job context and your profile.",
    status: "planned",
    priority: "P1",
    module: "Cover Letter Intelligence",
    highlights: ["Job-aware drafts", "Tone control", "One-click from extension"],
    installable: false,
  },
  {
    id: "recruiter-crm",
    title: "Recruiter CRM",
    description: "Track recruiters, threads, and follow-up reminders.",
    status: "planned",
    priority: "P2",
    module: "Recruiter CRM",
    highlights: ["Contact management", "Follow-up scheduling", "Email integration"],
    installable: false,
  },
  {
    id: "interview-os",
    title: "Interview OS",
    description: "Mock interviews, prep checklists, and behavioral story bank.",
    status: "planned",
    priority: "P2",
    module: "Interview OS",
    highlights: ["Mock interview scaffolding", "Story bank", "Prep timelines"],
    installable: false,
  },
  {
    id: "career-analytics",
    title: "Career Analytics",
    description: "Funnel metrics, response rates, and activity timelines.",
    status: "planned",
    priority: "P2",
    module: "Career Analytics",
    highlights: ["Apply funnel", "Response rates", "Event tracking"],
    installable: false,
  },
  {
    id: "career-coach",
    title: "Career AI Coach",
    description: "Guidance across search, apply, interview, and negotiation.",
    status: "planned",
    priority: "P2",
    module: "Career AI Coach",
    highlights: ["Context-aware advice", "Role targeting", "Skill gap hints"],
    installable: false,
  },
  {
    id: "networking",
    title: "Networking Graph",
    description: "Relationships, referrals, and warm intro paths.",
    status: "planned",
    priority: "P3",
    module: "Networking",
    highlights: ["Referral tracking", "Relationship map", "Intro requests"],
    installable: false,
  },
  {
    id: "portfolio-builder",
    title: "Portfolio Builder",
    description: "Projects, case studies, and public profile site export.",
    status: "planned",
    priority: "P3",
    module: "Portfolio Builder",
    highlights: ["Project showcase", "Case study templates", "Public export"],
    installable: false,
  },
];

export type SupportedBrowser = "chrome" | "edge" | "firefox" | "brave" | "opera";

export interface BrowserInstallTarget {
  id: SupportedBrowser;
  name: string;
  engine: "chromium" | "firefox";
  available: boolean;
  installSteps: string[];
}

export const BROWSER_INSTALL_TARGETS: BrowserInstallTarget[] = [
  {
    id: "chrome",
    name: "Google Chrome",
    engine: "chromium",
    available: true,
    installSteps: [
      "Download the ApplyPilot package.",
      "Open chrome://extensions and enable Developer mode.",
      "Click Load unpacked and select the extracted folder, or drag the folder onto the page.",
      "ApplyPilot will connect to your CareerOS backend automatically.",
    ],
  },
  {
    id: "edge",
    name: "Microsoft Edge",
    engine: "chromium",
    available: true,
    installSteps: [
      "Download the ApplyPilot package.",
      "Open edge://extensions and enable Developer mode.",
      "Click Load unpacked and select the extracted folder.",
      "ApplyPilot will sync with the CareerOS API on first load.",
    ],
  },
  {
    id: "brave",
    name: "Brave",
    engine: "chromium",
    available: true,
    installSteps: [
      "Download the ApplyPilot package.",
      "Open brave://extensions and enable Developer mode.",
      "Load unpacked from the extracted folder.",
    ],
  },
  {
    id: "opera",
    name: "Opera",
    engine: "chromium",
    available: true,
    installSteps: [
      "Download the ApplyPilot package.",
      "Open opera://extensions and enable Developer mode.",
      "Load unpacked from the extracted folder.",
    ],
  },
  {
    id: "firefox",
    name: "Mozilla Firefox",
    engine: "firefox",
    available: true,
    installSteps: [
      "Download the Firefox ApplyPilot package.",
      "Open about:debugging#/runtime/this-firefox.",
      "Click Load Temporary Add-on and select manifest.json inside the extracted folder.",
      "For updates, remove the old add-on and load the new package.",
    ],
  },
];

export function getProductFeature(id: ProductFeatureId): ProductFeature | undefined {
  return PRODUCT_FEATURES.find((f) => f.id === id);
}
