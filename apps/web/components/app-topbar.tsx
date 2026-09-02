"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { BackendStatusDot } from "@/components/backend-status-dot";
import { NAV_GROUPS } from "@/lib/nav-config";
import { CareerIcon } from "@/components/ui/career-icon";
import { useBackendStatus } from "@/hooks/use-backend-status";

const DIRECT_ACTIONS = [
  { label: "Open dashboard", href: "/dashboard", detail: "Dashboard" },
  { label: "Open job scraper", href: "/jobs/discover", detail: "Job Scraper" },
  { label: "Open AI Assistant", href: "/application-assistant", detail: "AI Assistant" },
  { label: "Edit profile", href: "/profile", detail: "Profile" },
];

export function AppTopbar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const backendOnline = useBackendStatus();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);

  const items = useMemo(() => [
    ...DIRECT_ACTIONS.map((item) => ({ ...item, group: "Actions" })),
    ...NAV_GROUPS.flatMap((group) => group.items.map((item) => ({
      label: item.label,
      href: item.href,
      detail: group.label,
      group: "Navigate",
    }))),
  ], []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle
      ? items.filter((item) => `${item.label} ${item.detail}`.toLowerCase().includes(needle))
      : items;
  }, [items, query]);

  const current = NAV_GROUPS.flatMap((group) => group.items).find((item) => {
    const target = new URL(item.href, "https://careeros.local");
    if (pathname !== target.pathname && !pathname.startsWith(`${target.pathname}/`)) return false;
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
  });

  useEffect(() => {
    const handle = (event: KeyboardEvent) => {
      if (pathname === "/resume-corpus" || pathname.startsWith("/resume-corpus/")) return;
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    const previous = document.body.style.overflow;
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(
        'input, button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
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
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", trapFocus);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", trapFocus);
    };
  }, [open]);

  useEffect(() => setActiveIndex(0), [query]);

  const close = () => {
    setOpen(false);
    window.requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const choose = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  return (
    <>
      <header className="app-topbar">
        <div className="app-topbar-context">
          <Link href={current?.href ?? "/dashboard"}>{current?.label ?? "CareerOS"}</Link>
          <span aria-hidden>/</span>
          <strong className="app-topbar-page-title">Dashboard</strong>
          <span className={`app-topbar-live-state${backendOnline === false ? " is-offline" : ""}`}>
            <BackendStatusDot />
            {backendOnline === false ? "Offline" : backendOnline === true ? "Running" : "Checking"}
          </span>
        </div>
        <div className="app-topbar-actions">
          <button
            ref={triggerRef}
            type="button"
            className="app-topbar-search"
            aria-haspopup="dialog"
            aria-expanded={open}
            aria-controls="global-command-dialog"
            onClick={() => setOpen(true)}
          >
            <CareerIcon name="search" size={16} />
            <span>Search jobs, companies, roles…</span>
            <kbd>⌘ K</kbd>
          </button>
          <Link className="app-topbar-icon-button" href="/applications?tab=review" aria-label="Open Review Center">
            <CareerIcon name="bell" size={18} />
          </Link>
          <Link className="app-topbar-avatar" href="/profile" aria-label="Open your profile">C</Link>
        </div>
      </header>

      {open ? (
        <div className="command-layer" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) close();
        }}>
          <section
            ref={dialogRef}
            id="global-command-dialog"
            className="command-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="global-command-title"
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                close();
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((index) => Math.min(index + 1, filtered.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((index) => Math.max(index - 1, 0));
              } else if (event.key === "Enter" && filtered[activeIndex]) {
                event.preventDefault();
                choose(filtered[activeIndex].href);
              }
            }}
          >
            <div className="command-input-row">
              <CareerIcon name="search" size={19} />
              <label id="global-command-title" className="sr-only" htmlFor="global-command-input">Search CareerOS</label>
              <input
                ref={inputRef}
                id="global-command-input"
                value={query}
                onChange={(event) => setQuery(event.currentTarget.value)}
                placeholder="Search workflows and actions"
                autoComplete="off"
                role="combobox"
                aria-autocomplete="list"
                aria-expanded="true"
                aria-controls="global-command-results"
                aria-activedescendant={filtered[activeIndex] ? `global-command-option-${activeIndex}` : undefined}
              />
              <button type="button" aria-label="Close search" onClick={close}><CareerIcon name="close" size={18} /></button>
            </div>
            <div id="global-command-results" className="command-results" role="listbox" aria-label="CareerOS commands">
              {filtered.length ? filtered.map((item, index) => (
                <button
                  id={`global-command-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={index === activeIndex}
                  className={index === activeIndex ? "is-active" : ""}
                  key={`${item.group}-${item.href}-${item.label}`}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => choose(item.href)}
                >
                  <span><strong>{item.label}</strong><small>{item.detail}</small></span>
                  <CareerIcon name="arrow" size={16} />
                </button>
              )) : <p className="command-empty">No matching workflow. Try “applications” or “evidence.”</p>}
            </div>
            <footer className="command-footer"><span>↑↓ Move</span><span>Enter Open</span><span>Esc Close</span></footer>
          </section>
        </div>
      ) : null}
    </>
  );
}

