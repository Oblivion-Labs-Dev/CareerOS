"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/ui/theme-toggle";

const NAV_GROUPS = [
  {
    label: "Overview",
    items: [{ href: "/roadmap", label: "Roadmap", icon: "R" }],
  },
  {
    label: "Foundation",
    items: [
      { href: "/profile", label: "Profile", icon: "P" },
      { href: "/referrals", label: "Referrals", icon: "R" },
      { href: "/resumes", label: "Documents", icon: "D" },
      { href: "/settings", label: "Settings", icon: "S" },
    ],
  },
  {
    label: "Apply",
    items: [
      { href: "/apply-pilot", label: "ApplyPilot", icon: "AP" },
      { href: "/applications", label: "Application Tracker", icon: "AT" },
      { href: "/jobs", label: "Jobs", icon: "J" },
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

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <Link href="/" className="brand">
          <span className="brand-mark">OS</span>
          CareerOS
        </Link>
        <ThemeToggle />
      </div>
      <div className="brand-sub">A clear operating system for the whole career search.</div>
      <nav className="sidebar-nav" aria-label="CareerOS sections">
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group.label}>
            <div className="nav-group-label">{group.label}</div>
            {group.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`nav-link${pathname === item.href ? " active" : ""}`}
                prefetch
              >
                <span className="nav-icon" aria-hidden>
                  {item.icon}
                </span>
                {item.label}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <Link href="/" className="btn-ghost" style={{ width: "100%", justifyContent: "center" }}>
          Back to home
        </Link>
      </div>
    </aside>
  );
}
