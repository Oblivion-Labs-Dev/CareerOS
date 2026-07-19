"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { BackendIcon } from "@/components/backend-icon";
import { BackendNavTooltip } from "@/components/backend-nav-tooltip";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { CareerIcon } from "@/components/ui/career-icon";
import { useBackendStatus } from "@/hooks/use-backend-status";
import { NAV_GROUPS } from "@/lib/nav-config";

export function AppSidebar() {
  const pathname = usePathname();
  const backendOnline = useBackendStatus();
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
        ? "Backend offline — start API server"
        : "Checking backend…";

  return (
    <>
      <header className="app-mobile-header">
        <Link href="/dashboard" className="brand" aria-label="CareerOS Command Center">
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
        <Link href="/dashboard" className="brand" aria-label="CareerOS Command Center">
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
      <div className="brand-sub">One focused loop from evidence to outcome.</div>
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
                  onClick={() => setMobileOpen(false)}
                >
                  <span className="nav-icon" aria-hidden>
                    <CareerIcon name={item.icon} size={18} />
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
        <Link href="/" className="btn-ghost sidebar-home-link">
          View product home
        </Link>
      </div>
      </aside>
    </>
  );
}
