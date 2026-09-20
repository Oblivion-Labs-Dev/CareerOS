"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import styles from "./title-filter-dropdown.module.css";

interface TitleFilterDropdownProps {
  value: string;
  onChange: (title: string) => void;
  titles: [string, number][]; // [jobTitle, jobCount]
  totalCount: number;
}

export function TitleFilterDropdown({
  value,
  onChange,
  titles,
  totalCount,
}: TitleFilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Close when clicking outside
  useEffect(() => {
    if (!open) return undefined;
    const onMouseDown = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [open]);

  // Keyboard navigation: Escape closes
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  // Focus search input when opened
  useEffect(() => {
    if (open) {
      setSearch("");
      const timer = setTimeout(() => {
        searchInputRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [open]);

  // Filter title list in popup if user types in the filter box
  const filteredTitles = useMemo(() => {
    if (!search.trim()) return titles;
    const q = search.trim().toLowerCase();
    return titles.filter(([title]) => title.toLowerCase().includes(q));
  }, [titles, search]);

  const selectedCount = useMemo(() => {
    if (!value) return totalCount;
    const found = titles.find(([t]) => t.toLowerCase() === value.toLowerCase());
    return found ? found[1] : 0;
  }, [value, titles, totalCount]);

  const handleSelect = (title: string) => {
    onChange(title);
    setOpen(false);
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation();
    onChange("");
  };

  return (
    <div className={styles.container} ref={dropdownRef}>
      <button
        type="button"
        className={`${styles.triggerBtn} ${value ? styles.triggerBtnActive : ""}`}
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Filter applications by role title"
      >
        {/* Role/Badge Icon */}
        <svg
          className={styles.icon}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="16 18 22 12 16 6" />
          <polyline points="8 6 2 12 8 18" />
        </svg>

        <span className={styles.label}>{value || "All Titles"}</span>

        <span className={styles.badge}>{selectedCount}</span>

        {value && (
          <button
            type="button"
            className={styles.clearBtn}
            onClick={handleClear}
            title="Clear title filter"
            aria-label="Clear title filter"
          >
            ✕
          </button>
        )}

        <svg
          className={`${styles.chevron} ${open ? styles.chevronOpen : ""}`}
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {open && (
        <div className={styles.menu} role="listbox">
          {titles.length > 7 && (
            <div className={styles.menuHeader}>
              <div className={styles.filterInputWrap}>
                <svg
                  className={styles.searchIcon}
                  viewBox="0 0 20 20"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <circle cx="9" cy="9" r="6" />
                  <line x1="13.5" y1="13.5" x2="18" y2="18" />
                </svg>
                <input
                  ref={searchInputRef}
                  type="text"
                  className={styles.filterInput}
                  placeholder="Filter job titles…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className={styles.list}>
            {/* Option to select All Titles */}
            {(!search.trim() || "all titles".includes(search.toLowerCase().trim())) && (
              <button
                type="button"
                className={`${styles.item} ${!value ? styles.itemActive : ""}`}
                onClick={() => handleSelect("")}
                role="option"
                aria-selected={!value}
              >
                <span className={styles.itemName}>
                  {!value ? (
                    <svg className={styles.checkIcon} viewBox="0 0 20 20" fill="currentColor">
                      <path
                        fillRule="evenodd"
                        d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
                        clipRule="evenodd"
                      />
                    </svg>
                  ) : (
                    <span className={styles.emptyCheck} />
                  )}
                  All Titles
                </span>
                <span className={styles.itemCount}>{totalCount}</span>
              </button>
            )}

            {/* Individual job title options */}
            {filteredTitles.map(([title, count]) => {
              const isSelected = value.toLowerCase() === title.toLowerCase();
              return (
                <button
                  key={title}
                  type="button"
                  className={`${styles.item} ${isSelected ? styles.itemActive : ""}`}
                  onClick={() => handleSelect(title)}
                  role="option"
                  aria-selected={isSelected}
                >
                  <span className={styles.itemName} title={title}>
                    {isSelected ? (
                      <svg className={styles.checkIcon} viewBox="0 0 20 20" fill="currentColor">
                        <path
                          fillRule="evenodd"
                          d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
                          clipRule="evenodd"
                        />
                      </svg>
                    ) : (
                      <span className={styles.emptyCheck} />
                    )}
                    {title}
                  </span>
                  <span className={styles.itemCount}>{count}</span>
                </button>
              );
            })}

            {filteredTitles.length === 0 && search.trim() && (
              <div className={styles.emptyState}>No titles match &ldquo;{search}&rdquo;</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
