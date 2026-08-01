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
export const VISIBLE_NAV_HREFS = ["/dashboard", "/jobs/discover", "/profile", "/application-assistant", "/analytics"] as const;

/** Full nav catalog — routes stay available; disabled items appear under Coming soon. */
export const ALL_NAV_GROUPS: NavGroup[] = [
  {
    label: "Today",
    items: [{ href: "/dashboard", label: "Dashboard", icon: "today", emoji: "📊", requiresBackend: true, enabled: true }],
  },
  {
    label: "Intelligence Layer",
    items: [
      { href: "/jobs/discover", label: "Job Scraper", icon: "jobs", emoji: "🔎", requiresBackend: true, enabled: true },
      { href: "/application-assistant", label: "AI Assistant", icon: "applypilot", emoji: "🤖", requiresBackend: true, enabled: true },
      { href: "/intelligence/signals", label: "Signals", icon: "insights", requiresBackend: true, enabled: false },
      { href: "/intelligence/night-shift", label: "Night Shift", icon: "applypilot", requiresBackend: true, enabled: false },
      { href: "/intelligence/auto-apply", label: "Auto Apply", icon: "applypilot", requiresBackend: true, enabled: false },
      { href: "/intelligence/tasks", label: "Daily Tasks", icon: "today", requiresBackend: true, enabled: false },
    ],
  },
  {
    label: "Build",
    items: [
      { href: "/profile", label: "Profile", icon: "profile", emoji: "👤", requiresBackend: true, enabled: true },
      { href: "/resumes", label: "Documents", icon: "documents", requiresBackend: true, enabled: false },
      { href: "/resume-scanner", label: "Resume Scanner", icon: "evidence", emoji: "📄", requiresBackend: true, enabled: false },
      { href: "/resume-corpus", label: "Resume Intelligence", icon: "evidence", requiresBackend: true, enabled: false },
      { href: "/intelligence/answers", label: "Answer Bank", icon: "documents", requiresBackend: true, enabled: false },
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
      { href: "/networking", label: "Relationships", icon: "relationships", requiresBackend: true, enabled: false },
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

function visibleNavGroups(groups: NavGroup[]): NavGroup[] {
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => item.enabled !== false),
    }))
    .filter((group) => group.items.length > 0);
}

/** Sidebar + command palette — enabled pages only. */
export const NAV_GROUPS = visibleNavGroups(ALL_NAV_GROUPS);

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
  return ALL_NAV_GROUPS.some((group) =>
    group.items.some(
      (item) =>
        item.requiresBackend &&
        (pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`))),
    ),
  );
}
