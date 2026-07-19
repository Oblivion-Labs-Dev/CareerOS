export interface NavItem {
  href: string;
  label: string;
  icon: string;
  requiresBackend?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Today",
    items: [{ href: "/dashboard", label: "Command Center", icon: "today", requiresBackend: true }],
  },
  {
    label: "Build",
    items: [
      { href: "/profile", label: "Profile", icon: "profile", requiresBackend: true },
      { href: "/resumes", label: "Documents", icon: "documents", requiresBackend: true },
      { href: "/resume-corpus", label: "Resume Intelligence", icon: "evidence", requiresBackend: true },
    ],
  },
  {
    label: "Search & apply",
    items: [
      { href: "/jobs", label: "Opportunities", icon: "jobs", requiresBackend: true },
      { href: "/applications", label: "Applications", icon: "applications", requiresBackend: true },
    ],
  },
  {
    label: "Connect & prepare",
    items: [
      { href: "/networking", label: "Relationships", icon: "relationships", requiresBackend: true },
      { href: "/interviews", label: "Interviews", icon: "interviews", requiresBackend: true },
      { href: "/analytics", label: "Progress & Insights", icon: "insights", requiresBackend: true },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/apply-pilot", label: "ApplyPilot", icon: "applypilot", requiresBackend: true },
      { href: "/apply/job-search-guide", label: "Resources", icon: "resources" },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/settings", label: "Settings", icon: "settings" },
      { href: "/roadmap", label: "Roadmap", icon: "roadmap" },
    ],
  },
];

export const BACKEND_NAV_TOOLTIP =
  "If you're running CareerOS locally, this page needs the backend server to function.";

export const BACKEND_BANNER_ONLINE =
  "If running locally, keep the backend server running while you use this page.";

export const BACKEND_BANNER_OFFLINE =
  "If running locally, this page needs the backend server to function. Start it in a terminal, then refresh.";

export const BACKEND_START_COMMAND = `cd CareerOS/apps/api
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`;

export function pathRequiresBackend(pathname: string): boolean {
  return NAV_GROUPS.some((group) =>
    group.items.some(
      (item) =>
        item.requiresBackend &&
        (pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`))),
    ),
  );
}
