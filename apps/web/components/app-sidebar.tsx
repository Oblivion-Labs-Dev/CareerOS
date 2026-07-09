"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BackendIcon } from "@/components/backend-icon";
import { BackendNavTooltip } from "@/components/backend-nav-tooltip";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { NAV_GROUPS } from "@/lib/nav-config";

export function AppSidebar() {
  const pathname = usePathname();
  const backendOnline = useBackendStatus();

  const legendText =
    backendOnline === true
      ? "Backend connected"
      : backendOnline === false
        ? "Backend offline — start API server"
        : "Checking backend…";

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
            {group.items.map((item) => {
              const isActive =
                pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`nav-link${isActive ? " active" : ""}`}
                  prefetch
                  title={item.label}
                >
                  <span className="nav-icon" aria-hidden>
                    {item.icon}
                  </span>
                  <span className="nav-link-label">{item.label}</span>
                  {item.requiresBackend ? <BackendNavTooltip online={backendOnline} /> : null}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="sidebar-footer">
        <p
          className={`sidebar-backend-legend${backendOnline ? " sidebar-backend-legend--online" : ""}`}
          title={legendText}
        >
          <BackendIcon className="sidebar-backend-legend-icon" title="" />
          {legendText}
        </p>
        <Link href="/" className="btn-ghost" style={{ width: "100%", justifyContent: "center" }}>
          Back to home
        </Link>
      </div>
    </aside>
  );
}
