"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { BackendStatusDot } from "@/components/backend-status-dot";
import { CareerIcon } from "@/components/ui/career-icon";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { formatNavCount, sidebarCountForHref, useSidebarJobCounts } from "@/hooks/use-sidebar-job-counts";
import styles from "./app-sidebar.module.css";
import { NAV_GROUPS } from "@/lib/nav-config";
import { getAuthStatus, logout } from "@/lib/auth-api";

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
    return !activeTab || !["inbox", "pipeline", "tracker"].includes(activeTab);
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
  const [authRequired, setAuthRequired] = useState(false);

  useEffect(() => {
    getAuthStatus().then((status) => setAuthRequired(status.authRequired));
  }, []);

  const handleLogout = async () => {
    await logout();
    window.location.href = "/login";
  };

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
        'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
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

  const brand = (
    <Link href="/dashboard" className="brand" aria-label="CareerOS Dashboard">
      <span className="brand-mark" aria-hidden><span className="brand-orbit" /></span>
      CareerOS
    </Link>
  );

  return (
    <>
      <header className="app-mobile-header">
        {brand}
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
        className={`${styles.rail} sidebar${mobileOpen ? " sidebar--mobile-open" : ""}`}
        role={mobileViewport && mobileOpen ? "dialog" : undefined}
        aria-modal={mobileViewport && mobileOpen ? true : undefined}
        aria-label={mobileViewport && mobileOpen ? "CareerOS navigation" : undefined}
        aria-hidden={mobileViewport && !mobileOpen ? true : undefined}
        inert={mobileViewport && !mobileOpen ? true : undefined}
      >
        <div className="sidebar-header">
          {brand}
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
              {group.items.filter(item => item.enabled !== false).map((item) => {
                const isDisabled = item.enabled === false;
                const active = !isDisabled && isItemActive(pathname, searchParams, item.href);
                const count = sidebarCountForHref(item.href, counts);
                const showCount = !isDisabled && backendOnline !== false && loaded && count !== null && count > 0;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`nav-link${active ? " active" : ""}`}
                    aria-current={active ? "page" : undefined}
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

        <div className={styles.bottom}>
          <details className={styles.archived}>
            <summary><span className={styles.archiveIcon} aria-hidden="true">◫</span><span>Disabled pages</span><span className={styles.archiveCount}>{NAV_GROUPS.flatMap(group => group.items).filter(item => item.enabled === false).length}</span><span className={styles.chevron} aria-hidden="true">⌄</span></summary>
            <div className={styles.archiveList}>
              {NAV_GROUPS.flatMap(group => group.items).filter(item => item.enabled === false).map(item => (
                <div key={item.href} className={styles.disabledItem} aria-disabled="true"><CareerIcon name={item.icon} size={15} /><span>{item.label}</span><span className={styles.disabledTag}>Off</span></div>
              ))}
            </div>
          </details>
          <footer className={styles.footer}>
            <span className={styles.connection} title={backendText}><BackendStatusDot /><span>{backendText}</span></span>
            {authRequired && <button type="button" onClick={() => void handleLogout()}>Sign out ↗</button>}
          </footer>
        </div>
      </aside>
    </>
  );
}
