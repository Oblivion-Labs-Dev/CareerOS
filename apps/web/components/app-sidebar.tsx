"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { BackendStatusDot } from "@/components/backend-status-dot";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { CareerIcon } from "@/components/ui/career-icon";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { formatNavCount, sidebarCountForHref, useSidebarJobCounts } from "@/hooks/use-sidebar-job-counts";
import { NAV_GROUPS } from "@/lib/nav-config";

function isItemActive(pathname: string, searchParams: URLSearchParams, href: string) {
  const target = new URL(href, "https://careeros.local");
  const pathMatches = pathname === target.pathname || (
    target.pathname !== "/" && pathname.startsWith(`${target.pathname}/`)
  );
  if (!pathMatches) return false;

  const tab = target.searchParams.get("tab");
  const section = target.searchParams.get("section");
  if (tab) return searchParams.get("tab") === tab;
  if (section) return searchParams.get("section") === section;
  if (target.pathname === "/applications") {
    const activeTab = searchParams.get("tab");
    return !activeTab || activeTab === "autopilot";
  }
  if (target.pathname === "/settings") return !searchParams.get("section");
  return true;
}

export function AppSidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const backendOnline = useBackendStatus();
  const { counts, loaded } = useSidebarJobCounts();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileViewport, setMobileViewport] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const openButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const update = () => {
      setMobileViewport(query.matches);
      if (!query.matches) setMobileOpen(false);
    };
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => setMobileOpen(false), [pathname, searchParams]);

  useEffect(() => {
    if (!mobileViewport || !mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => closeButtonRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileOpen(false);
        window.requestAnimationFrame(() => openButtonRef.current?.focus());
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const focusable = [...drawerRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )];
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [mobileOpen, mobileViewport]);

  const backendText = backendOnline === true
    ? "Backend connected"
    : backendOnline === false
      ? "Backend offline"
      : "Checking backend…";

  return (
    <>
      <header className="app-mobile-header">
        <Link href="/dashboard" className="brand" aria-label="CareerOS Dashboard">
          <span className="brand-mark"><span className="brand-orbit" /></span>
          CareerOS
        </Link>
        <button
          ref={openButtonRef}
          type="button"
          className="app-mobile-menu-button"
          aria-label="Open CareerOS navigation"
          aria-controls="careeros-primary-navigation"
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen(true)}
        >
          <CareerIcon name="menu" size={17} /> Menu
        </button>
      </header>

      {mobileOpen ? (
        <button type="button" className="sidebar-backdrop" aria-label="Close CareerOS navigation" onClick={() => setMobileOpen(false)} />
      ) : null}

      <aside
        ref={drawerRef}
        id="careeros-primary-navigation"
        className={`sidebar${mobileOpen ? " sidebar--mobile-open" : ""}`}
        role={mobileViewport && mobileOpen ? "dialog" : undefined}
        aria-modal={mobileViewport && mobileOpen ? true : undefined}
        aria-label={mobileViewport && mobileOpen ? "CareerOS navigation" : undefined}
        aria-hidden={mobileViewport && !mobileOpen ? true : undefined}
        inert={mobileViewport && !mobileOpen ? true : undefined}
      >
        <div className="sidebar-header">
          <Link href="/dashboard" className="brand" aria-label="CareerOS Dashboard">
            <span className="brand-mark"><span className="brand-orbit" /></span>
            CareerOS
          </Link>
          <button
            ref={closeButtonRef}
            type="button"
            className="sidebar-close-button"
            aria-label="Close CareerOS navigation"
            onClick={() => {
              setMobileOpen(false);
              window.requestAnimationFrame(() => openButtonRef.current?.focus());
            }}
          >
            <CareerIcon name="close" size={18} />
          </button>
        </div>

        <nav className="sidebar-nav" aria-label="CareerOS sections">
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.label}>
              <div className="nav-group-label">{group.label}</div>
              {group.items.map((item) => {
                const active = isItemActive(pathname, searchParams, item.href);
                const count = sidebarCountForHref(item.href, counts);
                const showCount = backendOnline !== false && loaded && count !== null && count > 0;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`nav-link${active ? " active" : ""}`}
                    title={showCount ? `${item.label} — ${count.toLocaleString()} items` : item.label}
                    onClick={() => setMobileOpen(false)}
                  >
                    <span className="nav-icon" aria-hidden><CareerIcon name={item.icon} size={18} /></span>
                    <span className="nav-link-label">{item.label}</span>
                    {showCount ? <span className="nav-link-count">{formatNavCount(count)}</span> : null}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <footer className="sidebar-footer">
          <div className="sidebar-night-card">
            <div className="sidebar-night-card-head">
              <span><strong>Night Mode</strong><small>Active</small></span>
              <span className="sidebar-night-icon"><CareerIcon name="moon" size={17} /></span>
            </div>
            <p>Autopilot performs best during night hours.</p>
            <ThemeToggle />
          </div>

          <div className="sidebar-profile-card">
            <span className="sidebar-avatar">C</span>
            <span className="sidebar-profile-copy">
              <strong>Your workspace</strong>
              <small>Private local operator</small>
            </span>
          </div>

          <p className="sidebar-backend-legend" title={backendText}>
            <BackendStatusDot />
            <span className="sidebar-backend-legend-label">{backendText}</span>
          </p>
        </footer>
      </aside>
    </>
  );
}
