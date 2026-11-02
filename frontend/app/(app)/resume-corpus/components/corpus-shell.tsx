"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import type { CorpusSummary } from "../corpus-model";
import {
  COMING_SOON_FEATURES,
  CORPUS_VIEW_LABELS,
  type ComingSoonFeature,
  type ComingSoonFeatureId,
  type CorpusView,
} from "../corpus-navigation";
import styles from "../resume-corpus.module.css";

interface NavItem {
  id: CorpusView;
  label: string;
  shortLabel: string;
  icon: string;
  count?: number;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

interface CorpusShellProps {
  activeView: CorpusView;
  activeComingSoon?: ComingSoonFeature;
  summary: CorpusSummary;
  collapsed: boolean;
  mobileOpen: boolean;
  previewMode: boolean;
  statusLabel: string;
  onCollapsedChange: (collapsed: boolean) => void;
  onMobileOpenChange: (open: boolean) => void;
  onNavigate: (view: CorpusView) => void;
  onOpenComingSoon: (featureId: ComingSoonFeatureId) => void;
  onOpenSearch: () => void;
  onCreate: () => void;
  children: ReactNode;
}

export function CorpusShell({
  activeView,
  activeComingSoon,
  summary,
  collapsed,
  mobileOpen,
  previewMode,
  statusLabel,
  onCollapsedChange,
  onMobileOpenChange,
  onNavigate,
  onOpenComingSoon,
  onOpenSearch,
  onCreate,
  children,
}: CorpusShellProps) {
  const navRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const railRef = useRef<HTMLElement>(null);
  const mobileCloseRef = useRef<HTMLButtonElement>(null);
  const previousMobileFocusRef = useRef<HTMLElement | null>(null);
  const [mobileViewport, setMobileViewport] = useState(false);
  const [comingSoonOpen, setComingSoonOpen] = useState(false);

  useEffect(() => {
    if (activeComingSoon) setComingSoonOpen(true);
  }, [activeComingSoon]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 760px)");
    const update = () => setMobileViewport(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!mobileViewport || !mobileOpen) return;
    previousMobileFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = window.requestAnimationFrame(() => mobileCloseRef.current?.focus());
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onMobileOpenChange(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", closeOnEscape);
      previousMobileFocusRef.current?.focus();
    };
  }, [mobileOpen, mobileViewport, onMobileOpenChange]);

  const navGroups = useMemo<NavGroup[]>(() => [
    {
      label: "Phase 1",
      items: [
        { id: "overview", label: "Overview", shortLabel: "Home", icon: "OV" },
        { id: "accomplishments", label: "Accomplishments", shortLabel: "Work", icon: "AC", count: summary.total },
        { id: "metrics", label: "Metrics", shortLabel: "Metrics", icon: "MT", count: summary.missingMetrics || undefined },
        { id: "evidence", label: "Evidence", shortLabel: "Proof", icon: "EV" },
        { id: "interview", label: "Interview", shortLabel: "Practice", icon: "IN", count: summary.unansweredQuestions || undefined },
        { id: "settings", label: "Settings", shortLabel: "Settings", icon: "ST" },
      ],
    },
  ], [summary.missingMetrics, summary.total, summary.unansweredQuestions]);

  const comingSoonCategories = useMemo(
    () => Array.from(new Set(COMING_SOON_FEATURES.map((feature) => feature.category))),
    [],
  );

  const allItems = navGroups.flatMap((group) => group.items);

  const handleNavKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let targetIndex = index;
    if (event.key === "ArrowDown") targetIndex = (index + 1) % allItems.length;
    else if (event.key === "ArrowUp") targetIndex = (index - 1 + allItems.length) % allItems.length;
    else if (event.key === "Home") targetIndex = 0;
    else if (event.key === "End") targetIndex = allItems.length - 1;
    else return;
    event.preventDefault();
    navRefs.current[targetIndex]?.focus();
  };

  const trapMobileFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (!mobileViewport || !mobileOpen || event.key !== "Tab") return;
    const focusable = Array.from(railRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const navigate = (view: CorpusView) => {
    onNavigate(view);
    onMobileOpenChange(false);
  };

  const openComingSoon = (featureId: ComingSoonFeatureId) => {
    onOpenComingSoon(featureId);
    onMobileOpenChange(false);
  };

  const toggleComingSoon = () => {
    if (collapsed) onCollapsedChange(false);
    setComingSoonOpen((open) => !open);
  };

  const mobileItems: Array<{ id?: CorpusView; label: string; icon: string }> = [
    { id: "overview", label: "Overview", icon: "OV" },
    { id: "accomplishments", label: "Work", icon: "AC" },
    { id: "metrics", label: "Metrics", icon: "MT" },
    { id: "evidence", label: "Evidence", icon: "EV" },
    { id: "interview", label: "Interview", icon: "IN" },
  ];

  let itemIndex = -1;

  return (
    <div className={`${styles.root} resume-corpus-app`}>
      <a href="#corpus-main" className={styles.skipLink}>Skip to corpus workspace</a>
      <div className={`${styles.appGrid} ${collapsed ? styles.appGridCollapsed : ""}`}>
        <aside
          ref={railRef}
          className={`${styles.rail} ${mobileOpen ? styles.railOpen : ""}`}
          aria-label="Resume Corpus navigation"
          aria-hidden={mobileViewport && !mobileOpen ? true : undefined}
          aria-modal={mobileViewport && mobileOpen ? true : undefined}
          role={mobileViewport && mobileOpen ? "dialog" : undefined}
          inert={mobileViewport && !mobileOpen ? true : undefined}
          onKeyDown={trapMobileFocus}
        >
          <div className={styles.railHeader}>
            <Link href="/dashboard" className={styles.brandBlock} aria-label="Back to CareerOS dashboard">
              <span className={styles.brandMark} aria-hidden="true">CI</span>
              <span className={styles.brandText}>
                <strong>Career intelligence</strong>
                <span>Resume Corpus</span>
              </span>
            </Link>
            <button
              ref={mobileCloseRef}
              type="button"
              className={styles.iconButton}
              onClick={() => mobileOpen ? onMobileOpenChange(false) : onCollapsedChange(!collapsed)}
              aria-label={mobileOpen ? "Close navigation" : collapsed ? "Expand navigation" : "Collapse navigation"}
              aria-expanded={mobileOpen || !collapsed}
            >
              {mobileOpen ? "\u00d7" : collapsed ? ">" : "<"}
            </button>
          </div>

          <nav className={styles.railNav} aria-label="Corpus areas">
            {navGroups.map((group) => (
              <div className={styles.navGroup} key={group.label}>
                <div className={styles.navGroupLabel}>{group.label}</div>
                {group.items.map((item) => {
                  itemIndex += 1;
                  const currentIndex = itemIndex;
                  const active = !activeComingSoon && activeView === item.id;
                  return (
                    <button
                      key={item.id}
                      ref={(element) => { navRefs.current[currentIndex] = element; }}
                      type="button"
                      className={`${styles.navItem} ${active ? styles.navItemActive : ""}`}
                      onClick={() => navigate(item.id)}
                      onKeyDown={(event) => handleNavKeyDown(event, currentIndex)}
                      aria-current={active ? "page" : undefined}
                      title={collapsed ? item.label : undefined}
                    >
                      <span className={styles.navIcon} aria-hidden="true">{item.icon}</span>
                      <span className={styles.navLabel}>{item.label}</span>
                      {typeof item.count === "number" && item.count > 0 ? (
                        <span className={styles.navCount} aria-label={`${item.count} ${item.count === 1 ? "item" : "items"}`}>{item.count}</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ))}

            <div className={`${styles.navGroup} ${styles.comingSoonNavGroup}`}>
              <button
                type="button"
                className={styles.comingSoonNavToggle}
                onClick={toggleComingSoon}
                aria-expanded={comingSoonOpen}
                aria-controls="corpus-coming-soon-nav"
                title={collapsed ? "Coming Soon" : undefined}
              >
                <span className={styles.navLock} aria-hidden="true"><span /></span>
                <span className={styles.navLabel}>Coming Soon</span>
                <span className={styles.comingSoonNavBadge}>Planned</span>
                <span className={styles.comingSoonChevron} aria-hidden="true">{comingSoonOpen ? "-" : "+"}</span>
              </button>

              {comingSoonOpen ? (
                <div id="corpus-coming-soon-nav" className={styles.comingSoonNavList}>
                  {comingSoonCategories.map((category) => (
                    <div className={styles.comingSoonNavCategory} key={category}>
                      <div className={styles.comingSoonNavCategoryLabel}>{category}</div>
                      {COMING_SOON_FEATURES.filter((feature) => feature.category === category).map((feature) => {
                        const active = activeComingSoon?.id === feature.id;
                        return (
                          <button
                            key={feature.id}
                            type="button"
                            className={`${styles.comingSoonNavItem} ${active ? styles.comingSoonNavItemActive : ""}`}
                            onClick={() => openComingSoon(feature.id as ComingSoonFeatureId)}
                            aria-current={active ? "page" : undefined}
                            aria-label={`${feature.label}, coming soon preview`}
                            title={collapsed ? feature.label : undefined}
                          >
                            <span className={styles.comingSoonItemLock} aria-hidden="true"><span /></span>
                            <span className={styles.navLabel}>{feature.label}</span>
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </nav>

          <div className={styles.railFooter}>
            <Link className={styles.previewLink} href={previewMode ? "/resume-corpus" : "/resume-corpus?preview=1"}>
              <span aria-hidden="true">{previewMode ? "\u00d7" : "\u25ce"}</span>
              <span>{previewMode ? "Exit preview data" : "Explore sample corpus"}</span>
            </Link>
          </div>
        </aside>

        <div className={styles.mainColumn}>
          <header className={styles.topbar}>
            <div className={styles.pageIdentity}>
              <span>{activeComingSoon ? "Resume Corpus / Coming Soon" : `Resume Corpus / ${CORPUS_VIEW_LABELS[activeView]}`}</span>
              <strong>{activeComingSoon?.label ?? CORPUS_VIEW_LABELS[activeView]}</strong>
            </div>
            <button type="button" className={styles.searchButton} onClick={onOpenSearch}>
              <span className={styles.searchGlyph} aria-hidden="true">{"\u2315"}</span>
              <span className={styles.searchPlaceholder}>Search accomplishments, metrics, evidence, questions...</span>
              <kbd className={styles.shortcut}>Ctrl K</kbd>
            </button>
            <div className={styles.headerActions}>
              <span className={styles.saveState}><span className={styles.saveDot} aria-hidden="true" />{statusLabel}</span>
              <ThemeToggle />
              <button type="button" className={styles.primaryButton} onClick={onCreate}><span aria-hidden="true">+</span>New accomplishment</button>
              <button type="button" className={`${styles.iconButton} ${styles.mobileMenuButton}`} onClick={() => onMobileOpenChange(true)} aria-label="Open all corpus areas">{"\u2261"}</button>
            </div>
          </header>

          <main id="corpus-main" className={styles.content} tabIndex={-1}>{children as never}</main>
        </div>
      </div>

      <nav className={styles.mobileNav} aria-label="Quick corpus navigation">
        {mobileItems.map((item) => (
          <button
            key={item.label}
            type="button"
            data-active={!activeComingSoon && item.id === activeView ? "true" : "false"}
            onClick={() => item.id ? navigate(item.id) : onMobileOpenChange(true)}
            aria-current={!activeComingSoon && item.id === activeView ? "page" : undefined}
          >
            <strong aria-hidden="true">{item.icon}</strong>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

