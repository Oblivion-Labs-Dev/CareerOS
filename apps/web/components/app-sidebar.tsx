"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { BackendStatusDot } from "@/components/backend-status-dot";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { CareerIcon } from "@/components/ui/career-icon";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { formatNavCount, sidebarCountForHref, useSidebarJobCounts } from "@/hooks/use-sidebar-job-counts";
import { COMING_SOON_NAV_ITEMS, NAV_GROUPS } from "@/lib/nav-config";

export function AppSidebar() {
  const pathname = usePathname();
  const backendOnline = useBackendStatus();
  const { counts: sidebarCounts, loaded: sidebarCountsLoaded } = useSidebarJobCounts();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileViewport, setMobileViewport] = useState(false);
  const [comingSoonOpen, setComingSoonOpen] = useState(false);
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

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

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
      )].filter((element) => !element.hasAttribute("inert"));
      if (focusable.length === 0) return;
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

  const legendText =
    backendOnline === true
      ? "Backend connected"
      : backendOnline === false
        ? "Backend offline"
        : "Checking backend…";

  function navIcon(item: (typeof NAV_GROUPS)[number]["items"][number]) {
    if (item.emoji) {
      return <span className="nav-emoji">{item.emoji}</span>;
    }
    return <CareerIcon name={item.icon} size={18} />;
  }

  return (
    <>
      <header className="app-mobile-header">
        <Link href="/dashboard" className="brand" aria-label="CareerOS Dashboard">
          <span className="brand-mark"><CareerIcon name="spark" /></span>
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
          <CareerIcon name="menu" size={17} />
          Menu
        </button>
      </header>
      {mobileOpen ? (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label="Close CareerOS navigation"
          onClick={() => setMobileOpen(false)}
        />
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
          <span className="brand-mark"><CareerIcon name="spark" /></span>
          CareerOS
        </Link>
        <div className="sidebar-header-actions">
          <ThemeToggle />
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
      </div>
      <div className="brand-sub">Intelligence Layer + CareerOS — evidence to outcome.</div>
      <nav className="sidebar-nav" aria-label="CareerOS sections">
        {NAV_GROUPS.map((group) => (
          <div className="nav-group" key={group.label}>
            <div className="nav-group-label">{group.label}</div>
            {group.items.map((item) => {
              const isActive =
                pathname === item.href || (item.href !== "/" && pathname.startsWith(`${item.href}/`));
              const sidebarCount = sidebarCountForHref(item.href, sidebarCounts);
              const showSidebarCount = backendOnline !== false && sidebarCountsLoaded && sidebarCount !== null;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`nav-link${isActive ? " active" : ""}`}
                  prefetch
                  title={
                    showSidebarCount
                      ? `${item.label} — ${sidebarCount!.toLocaleString()} to review`
                      : item.label
                  }
                  onClick={() => setMobileOpen(false)}
                >
                  <span className="nav-icon" aria-hidden>
                    {navIcon(item)}
                  </span>
                  <span className="nav-link-label">{item.label}</span>
                  {showSidebarCount ? (
                    <span className="nav-link-meta">
                      <span className="nav-link-count" aria-label={`${sidebarCount!.toLocaleString()} to review`}>
                        {formatNavCount(sidebarCount!)}
                      </span>
                    </span>
                  ) : null}
                </Link>
              );
            })}
          </div>
        ))}

        {COMING_SOON_NAV_ITEMS.length > 0 ? (
          <div className="nav-group nav-group--coming-soon">
            <button
              type="button"
              className="nav-group-toggle"
              aria-expanded={comingSoonOpen}
              aria-controls="sidebar-coming-soon"
              onClick={() => setComingSoonOpen((open) => !open)}
            >
              <span className="nav-group-toggle-label">Coming soon</span>
              <span className="nav-group-toggle-meta">
                <span className="nav-group-count">{COMING_SOON_NAV_ITEMS.length}</span>
                <CareerIcon
                  name="arrow"
                  size={14}
                  className={`nav-group-chevron${comingSoonOpen ? " nav-group-chevron--open" : ""}`}
                />
              </span>
            </button>
            {comingSoonOpen ? (
              <div id="sidebar-coming-soon" className="nav-group-items">
                {COMING_SOON_NAV_ITEMS.map((item) => (
                  <span
                    key={item.href}
                    className="nav-link nav-link--coming-soon nav-link--disabled"
                    aria-disabled="true"
                    title={`${item.label} — coming soon`}
                  >
                    <span className="nav-icon" aria-hidden>
                      {item.emoji ? <span className="nav-emoji">{item.emoji}</span> : <CareerIcon name={item.icon} size={18} />}
                    </span>
                    <span className="nav-link-label">{item.label}</span>
                    <span className="nav-coming-soon-tag">{item.groupLabel}</span>
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </nav>
      <div className="sidebar-footer">
        <p className="sidebar-backend-legend" title={legendText}>
          <BackendStatusDot />
          <span className="sidebar-backend-legend-label">{legendText}</span>
        </p>
        <Link href="/" className="btn-ghost sidebar-home-link">
          View product home
        </Link>
      </div>
      </aside>
    </>
  );
}
