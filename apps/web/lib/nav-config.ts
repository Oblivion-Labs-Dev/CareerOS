export interface NavItem {
  href: string;
  label: string;
  icon: string;
  /** Sidebar emoji — shown instead of the SVG icon when set. */
  emoji?: string;
  requiresBackend?: boolean;
  /** When false, shown under Coming soon (visible, not clickable). */
  enabled?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export interface ComingSoonNavItem extends NavItem {
  groupLabel: string;
}

/** Pages active in sidebar, dashboard nav, and command palette. */
export const VISIBLE_NAV_HREFS = [
  "/dashboard",
  "/applications",
  "/jobs/discover",
  "/analytics",
  "/profile",
  "/intelligence/answers",
  "/settings",
] as const;

/** Full nav catalog — routes stay available; disabled items appear under Coming soon. */
export const ALL_NAV_GROUPS: NavGroup[] = [
  {
    label: "Today",
    items: [{ href: "/dashboard", label: "Dashboard", icon: "today", emoji: "📊", requiresBackend: true, enabled: true }],
  },
  {
    label: "Intelligence Layer",
    items: [
      { href: "/applications", label: "AI Autopilot", icon: "applypilot", emoji: "⚡", requiresBackend: true, enabled: true },
      { href: "/jobs/discover", label: "Browse Jobs", icon: "jobs", emoji: "🔎", requiresBackend: true, enabled: true },
      { href: "/application-assistant", label: "AI Assistant", icon: "applypilot", emoji: "🤖", requiresBackend: true, enabled: true },
      { href: "/benchmarks", label: "LLM Benchmarks", icon: "evidence", emoji: "⚡", requiresBackend: true, enabled: true },
      { href: "/benchmarks/matcher", label: "Matcher Benchmark", icon: "evidence", emoji: "🏁", requiresBackend: true, enabled: true },
      { href: "/dev/dummy-job", label: "Dummy Job Test Bed", icon: "evidence", emoji: "🧪", requiresBackend: true, enabled: true },
      { href: "/intelligence/signals", label: "Signals", icon: "insights", requiresBackend: true, enabled: false },
      { href: "/intelligence/night-shift", label: "Night Shift", icon: "applypilot", requiresBackend: true, enabled: false },
      { href: "/intelligence/auto-apply", label: "Auto Apply", icon: "applypilot", emoji: "🛫", requiresBackend: true, enabled: false },
      { href: "/intelligence/tasks", label: "Daily Tasks", icon: "today", requiresBackend: true, enabled: false },
    ],
  },
  {
    label: "Build",
    items: [
      { href: "/profile", label: "Profile", icon: "profile", emoji: "👤", requiresBackend: true, enabled: true },
      { href: "/resume-corpus", label: "Resume Intelligence", icon: "evidence", emoji: "🧠", requiresBackend: true, enabled: true },
      { href: "/resume-scanner", label: "Resume Scanner", icon: "evidence", emoji: "📄", requiresBackend: true, enabled: true },
      { href: "/resumes", label: "Documents", icon: "documents", emoji: "📁", requiresBackend: true, enabled: true },
      { href: "/intelligence/answers", label: "Answer Bank", icon: "documents", emoji: "💬", requiresBackend: true, enabled: true },
    ],
  },
  {
    label: "Search",
    items: [
      { href: "/jobs", label: "Saved Jobs", icon: "jobs", requiresBackend: true, enabled: false },
      { href: "/jobs/target-companies", label: "Target Companies", icon: "jobs", requiresBackend: true, enabled: false },
    ],
  },
  {
    label: "Connect",
    items: [
      { href: "/referrals", label: "Referrals", icon: "relationships", requiresBackend: true, enabled: false },
      { href: "/recruiters", label: "Recruiter Outreach", icon: "relationships", requiresBackend: true, enabled: false },
      { href: "/networking", label: "Relationships", icon: "relationships", requiresBackend: true, enabled: true },
      { href: "/interviews", label: "Interviews", icon: "interviews", requiresBackend: true, enabled: false },
    ],
  },
  {
    label: "Insights",
    items: [{ href: "/analytics", label: "Progress & Insights", icon: "insights", emoji: "📈", requiresBackend: true, enabled: true }],
  },
  {
    label: "Tools",
    items: [
      { href: "/apply-pilot", label: "ApplyPilot", icon: "applypilot", requiresBackend: true, enabled: false },
      { href: "/cover-letters", label: "Cover Letters", icon: "documents", requiresBackend: true, enabled: false },
      { href: "/apply/job-search-guide", label: "Resources", icon: "resources", enabled: false },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/settings", label: "Settings", icon: "settings", enabled: false },
      { href: "/roadmap", label: "Roadmap", icon: "roadmap", enabled: false },
    ],
  },
];

/** Navigation used by the CareerOS mission-control shell.
 * `enabled: false` items still render (so it's visible what exists in the
 * repo) but are unclickable — see `app-sidebar.tsx`'s handling of this flag. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Main",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "today", requiresBackend: true, enabled: true },
      { href: "/applications", label: "Autopilot", icon: "applypilot", requiresBackend: true, enabled: true },
      { href: "/applications?tab=inbox", label: "Inbox", icon: "applications", requiresBackend: true, enabled: true },
      { href: "/applications?tab=pipeline", label: "Pipeline", icon: "applications", requiresBackend: true, enabled: true },
      { href: "/jobs/discover", label: "Browse Jobs", icon: "search", requiresBackend: true, enabled: true },
      { href: "/intelligence/auto-apply", label: "Auto Apply", icon: "applypilot", requiresBackend: true, enabled: false },
      { href: "/applications?tab=tracker", label: "All Applications", icon: "applications", requiresBackend: true, enabled: false },
      { href: "/applications?tab=review", label: "Review Center", icon: "review", requiresBackend: true, enabled: false },
      { href: "/analytics", label: "Analytics", icon: "insights", requiresBackend: true, enabled: false },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/profile", label: "Resume & Profile", icon: "profile", requiresBackend: true, enabled: true },
      { href: "/settings", label: "Settings", icon: "settings", enabled: true },
      { href: "/resume-corpus", label: "Resume Intelligence", icon: "evidence", requiresBackend: true, enabled: false },
      { href: "/intelligence/answers", label: "AI Answers", icon: "answers", requiresBackend: true, enabled: false },
      { href: "/networking", label: "Networking", icon: "relationships", requiresBackend: true, enabled: false },
      { href: "/benchmarks", label: "LLM Benchmarks", icon: "evidence", requiresBackend: true, enabled: false },
      { href: "/dev/dummy-job", label: "Dummy Job Test Bed", icon: "evidence", requiresBackend: true, enabled: false },
      { href: "/settings?section=integrations", label: "Integrations", icon: "integrations", enabled: false },
    ],
  },
];

export const VISIBLE_NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

/** Disabled pages — visible in sidebar under collapsible Coming soon. */
export const COMING_SOON_NAV_ITEMS: ComingSoonNavItem[] = ALL_NAV_GROUPS.flatMap((group) =>
  group.items
    .filter((item) => item.enabled === false)
    .map((item) => ({ ...item, groupLabel: group.label })),
);

export const BACKEND_NAV_TOOLTIP =
  "If you're running CareerOS locally, this page needs the backend server to function.";

export const BACKEND_BANNER_ONLINE =
  "If running locally, keep the backend server running while you use this page.";

export const BACKEND_BANNER_OFFLINE =
  "If running locally, this page needs the backend server to function. Start it in a terminal, then refresh.";

export const BACKEND_START_COMMAND = `cd CareerOS
.\\restart-dev.bat`;

export function pathRequiresBackend(pathname: string): boolean {
  const cleanPathname = pathname.split("?", 1)[0];
  return ALL_NAV_GROUPS.some((group) =>
    group.items.some(
      (item) =>
        item.requiresBackend &&
        (cleanPathname === item.href || (item.href !== "/" && cleanPathname.startsWith(`${item.href}/`))),
    ),
  );
}
