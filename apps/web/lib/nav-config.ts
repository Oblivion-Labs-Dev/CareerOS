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
    label: "Overview",
    items: [{ href: "/roadmap", label: "Roadmap", icon: "R" }],
  },
  {
    label: "Foundation",
    items: [
      { href: "/profile", label: "Profile", icon: "P", requiresBackend: true },
      { href: "/referrals", label: "Referrals", icon: "R", requiresBackend: true },
      { href: "/resumes", label: "Documents", icon: "D" },
      { href: "/settings", label: "Settings", icon: "S" },
    ],
  },
  {
    label: "Apply",
    items: [
      { href: "/apply-pilot", label: "ApplyPilot", icon: "AP", requiresBackend: true },
      { href: "/apply/outreach", label: "Email Outreach", icon: "EO", requiresBackend: true },
      { href: "/applications", label: "Application Tracker", icon: "AT", requiresBackend: true },
      { href: "/jobs", label: "Jobs", icon: "J", requiresBackend: true },
      { href: "/apply/job-search-guide", label: "Job Search Guide", icon: "JG" },
    ],
  },
  {
    label: "Grow",
    items: [
      { href: "/networking", label: "Contacts", icon: "C" },
      { href: "/interviews", label: "Interviews", icon: "I" },
      { href: "/analytics", label: "Analytics", icon: "AN" },
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
