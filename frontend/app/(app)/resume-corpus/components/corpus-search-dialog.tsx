"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { CorpusSearchResult, SearchCategory } from "../corpus-model";
import type { CorpusView } from "../corpus-navigation";
import styles from "../resume-corpus.module.css";

const SAVED_SEARCHES = [
  "Missing metrics",
  "Weak ownership",
  "Staff-level accomplishments",
  "AI infrastructure",
  "Distributed systems",
  "Unanswered interview questions",
  "Missing evidence",
  "Low roast resistance",
  "Ready for resume",
  "Needs review",
];

const CATEGORY_CODES: Record<SearchCategory, string> = {
  Accomplishments: "AC",
  Metrics: "MT",
  Skills: "SK",
  Evidence: "EV",
  "Reviewer concerns": "RV",
  "Interview questions": "IQ",
};

interface CorpusSearchDialogProps {
  open: boolean;
  results: CorpusSearchResult[];
  onClose: () => void;
  onQueryChange: (query: string, category?: SearchCategory) => void;
  onSelectRecord: (recordId: string) => void;
  onNavigate: (view: CorpusView) => void;
  onCreate: () => void;
}

function Highlight({ text, query }: { text: string; query: string }) {
  const terms = query.trim().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return <>{text}</>;
  const escaped = terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const pattern = new RegExp(`(${escaped.join("|")})`, "gi");
  const matches = new Set(terms.map((term) => term.toLocaleLowerCase()));
  return (
    <>
      {text.split(pattern).map((part, index) => matches.has(part.toLocaleLowerCase())
        ? <mark className={styles.highlight} key={`${part}-${index}`}>{part}</mark>
        : <span key={`${part}-${index}`}>{part}</span>)}
    </>
  );
}

export function CorpusSearchDialog({
  open,
  results,
  onClose,
  onQueryChange,
  onSelectRecord,
  onNavigate,
  onCreate,
}: CorpusSearchDialogProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<SearchCategory | "all">("all");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const dialogRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try {
      const stored = window.localStorage.getItem("careeros:corpus:recent-searches");
      if (stored) setRecentSearches(JSON.parse(stored) as string[]);
    } catch {
      setRecentSearches([]);
    }
    window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => previousFocusRef.current?.focus();
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [results]);

  useEffect(() => {
    onQueryChange(query, category === "all" ? undefined : category);
  }, [category, onQueryChange, query]);

  const groupedResults = useMemo(() => {
    const groups = new Map<SearchCategory, CorpusSearchResult[]>();
    for (const result of results) groups.set(result.category, [...(groups.get(result.category) ?? []), result]);
    return [...groups.entries()];
  }, [results]);

  if (!open) return null;

  const rememberSearch = (value: string) => {
    const normalized = value.trim();
    if (!normalized) return;
    const next = [normalized, ...recentSearches.filter((item) => item !== normalized)].slice(0, 6);
    setRecentSearches(next);
    try {
      window.localStorage.setItem("careeros:corpus:recent-searches", JSON.stringify(next));
    } catch {
      // Search continues to work if storage is unavailable.
    }
  };

  const chooseResult = (result: CorpusSearchResult) => {
    rememberSearch(query);
    onSelectRecord(result.recordId);
    onClose();
  };

  const handleInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelectedIndex((index) => Math.min(results.length - 1, index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelectedIndex((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter" && results[selectedIndex]) {
      event.preventDefault();
      chooseResult(results[selectedIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    }
  };

  const trapFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
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

  const command = (label: string, description: string, code: string, action: () => void): ReactNode => (
    <button
      type="button"
      className={styles.searchResult}
      key={label}
      onClick={() => {
        action();
        onClose();
      }}
    >
      <span className={styles.resultIcon} aria-hidden="true">{code}</span>
      <span className={styles.resultCopy}><strong>{label}</strong><span>{description}</span></span>
      <span className={styles.resultCategory}>Action</span>
    </button>
  );

  return (
    <div
      className={styles.overlay}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className={styles.searchDialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="corpus-search-title"
        onKeyDown={trapFocus}
      >
        <h2 id="corpus-search-title" className={styles.srOnly}>Search the Resume Corpus</h2>
        <div className={styles.searchInputWrap}>
          <span className={styles.searchGlyph} aria-hidden="true">⌕</span>
          <input
            ref={inputRef}
            className={styles.searchInput}
            role="combobox"
            aria-expanded={results.length > 0}
            aria-controls="corpus-search-results"
            aria-activedescendant={results[selectedIndex] ? `corpus-result-${results[selectedIndex].id}` : undefined}
            placeholder="Search the entire career corpus..."
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            onKeyDown={handleInputKeyDown}
          />
          <select
            className={styles.searchFilter}
            value={category}
            onChange={(event) => setCategory(event.currentTarget.value as SearchCategory | "all")}
            aria-label="Filter search category"
          >
            <option value="all">Every category</option>
            {Object.keys(CATEGORY_CODES).map((item) => <option value={item} key={item}>{item}</option>)}
          </select>
          <button type="button" className={styles.iconButton} onClick={onClose} aria-label="Close search">×</button>
        </div>

        <div
          id="corpus-search-results"
          className={styles.searchResults}
          role={query.trim() && results.length > 0 ? "listbox" : undefined}
          aria-label={query.trim() && results.length > 0 ? "Corpus search results" : undefined}
        >
          {!query.trim() ? (
            <>
              <div className={styles.searchGroupLabel}>Quick actions</div>
              {command("Create accomplishment", "Capture a new outcome without leaving the workspace", "NEW", onCreate)}
              {command("Build a targeted resume", "Rank proven accomplishments for a role", "RB", () => onNavigate("builder"))}
              {command("Match a job description", "Compare explicit evidence to job requirements", "JM", () => onNavigate("match"))}
              {command("Open unanswered questions", "Practice the gaps reviewers are most likely to probe", "IQ", () => onNavigate("interview"))}
              {command("Filter weak bullets", "Open accomplishments sorted for readiness", "WK", () => onNavigate("accomplishments"))}
              {command("Reviewer concerns", "See what could still get challenged", "RV", () => onNavigate("reviews"))}
              {command("Metrics needing verification", "Validate claims before they land on a resume", "MT", () => onNavigate("metrics"))}
              {command("Evidence gaps", "Attach proof to stories that lack artifacts", "EV", () => onNavigate("evidence"))}
              {command("Knowledge graph", "Explore relationships across companies, skills, and metrics", "KG", () => onNavigate("graph"))}
              {command("Corpus settings", "Update positioning and target role", "ST", () => onNavigate("settings"))}

              {recentSearches.length > 0 ? (
                <>
                  <div className={styles.searchGroupLabel}>Recent searches</div>
                  <div className={styles.searchSuggestions}>
                    {recentSearches.map((item) => <button type="button" className={styles.suggestion} key={item} onClick={() => setQuery(item)}>{item}</button>)}
                  </div>
                </>
              ) : null}

              <div className={styles.searchGroupLabel}>Saved searches</div>
              <div className={styles.searchSuggestions}>
                {SAVED_SEARCHES.map((item) => (
                  <button
                    type="button"
                    className={styles.suggestion}
                    key={item}
                    onClick={() => {
                      setCategory("all");
                      setQuery(item);
                    }}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </>
          ) : results.length === 0 ? (
            <StateMessage>No matches for “{query}”. Try a company, metric, skill, reviewer concern, or interview question.</StateMessage>
          ) : (
            groupedResults.map(([group, groupResults]) => (
              <div role="group" aria-labelledby={`search-group-${group.replace(/\s/g, "-")}`} key={group}>
                <div className={styles.searchGroupLabel} id={`search-group-${group.replace(/\s/g, "-")}`}>{group}</div>
                {groupResults.map((result) => {
                  const flatIndex = results.findIndex((candidate) => candidate.id === result.id);
                  return (
                    <button
                      type="button"
                      id={`corpus-result-${result.id}`}
                      role="option"
                      aria-selected={flatIndex === selectedIndex}
                      className={`${styles.searchResult} ${flatIndex === selectedIndex ? styles.searchResultActive : ""}`}
                      key={result.id}
                      onMouseEnter={() => setSelectedIndex(flatIndex)}
                      onClick={() => chooseResult(result)}
                    >
                      <span className={styles.resultIcon} aria-hidden="true">{CATEGORY_CODES[result.category]}</span>
                      <span className={styles.resultCopy}>
                        <strong><Highlight text={result.label} query={query} /></strong>
                        <span><Highlight text={result.snippet} query={query} /></span>
                      </span>
                      <span className={styles.resultCategory}>{result.category}</span>
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className={styles.searchFooter}>
          <span>↑↓ move · Enter open · Esc close</span>
          <span>{results.length} result{results.length === 1 ? "" : "s"}</span>
        </div>
      </div>
    </div>
  );
}

function StateMessage({ children }: { children: React.ReactNode }) {
  return <div className={styles.dialogBody} role="status"><p className={styles.resultsMeta}>{children as never}</p></div>;
}
