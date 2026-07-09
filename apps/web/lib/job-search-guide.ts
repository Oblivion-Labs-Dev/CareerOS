export interface JourneyStep {
  id: string;
  step: number;
  title: string;
  summary: string;
  tooltip?: string;
}

export const JOB_SEARCH_JOURNEY: JourneyStep[] = [
  {
    id: "prepare",
    step: 1,
    title: "Prepare your resume",
    summary: "Polish bullets and tailor for each role before you apply anywhere.",
    tooltip:
      "Start here. A strong resume with clear impact matters more than a perfect ATS scanner score.",
  },
  {
    id: "discover",
    step: 2,
    title: "Discover roles",
    summary: "Find Senior, Staff, and Principal openings on the best boards and AI matchers.",
    tooltip:
      "Use a mix of LinkedIn, Levels.fyi, and AI platforms — don't rely on one source.",
  },
  {
    id: "apply",
    step: 3,
    title: "Apply efficiently",
    summary: "Use autofill and a focused stack so each application is fast but tailored.",
    tooltip:
      "Quality over volume for senior roles. Tailor each resume rather than mass-applying blindly.",
  },
  {
    id: "outreach",
    step: 4,
    title: "Outreach & referrals",
    summary: "Most senior interviews come from people, not cold applications.",
    tooltip:
      "Employee referrals and recruiter replies often beat a hundred cold applications.",
  },
  {
    id: "track",
    step: 5,
    title: "Track & follow up",
    summary: "Stay organized and follow up on every promising thread.",
    tooltip: "Log every application and outreach so nothing falls through the cracks.",
  },
  {
    id: "understand",
    step: 6,
    title: "Play the long game",
    summary: "Know what ATS and recruiters actually evaluate — and how CareerOS helps.",
    tooltip:
      "Understanding the process helps you invest time where it actually converts to interviews.",
  },
];

export const GUIDE_TOOLTIPS = {
  atsScore:
    "Scanner scores use each tool's own rules — not a real ATS. Ignore the number; use the specific feedback.",
  jobscanMatch:
    "Aim for 70–80% keyword match. Missing nice-to-have keywords is fine; don't keyword-stuff.",
  aiMatching:
    "These tools analyze your resume, skills, and career path — not just keyword overlap.",
  worthUsing:
    "Yes = strongly recommended for senior engineers. Sometimes = useful but be selective.",
  coldVsWarm:
    "Cold apply = submitting on a job board. Warm = referral, recruiter reply, or direct outreach.",
  careerAgents:
    "Auto-apply tools help with volume. For senior Big Tech roles, review each application manually.",
  linkedInFocus:
    "Many senior engineers put ~70% of search effort on LinkedIn for discovery and recruiter visibility.",
} as const;
