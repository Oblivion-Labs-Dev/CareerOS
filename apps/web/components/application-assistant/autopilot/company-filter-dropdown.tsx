"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import styles from "./company-filter-dropdown.module.css";

interface CompanyFilterDropdownProps {
  value: string;
  onChange: (company: string) => void;
  companies: [string, number][]; // [companyName, jobCount]
  totalCount: number;
}

export function CompanyFilterDropdown({
  value,
  onChange,
  companies,
  totalCount,
}: CompanyFilterDropdownProps) {
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

  // Filter company list in popup if user types in the filter box
  const filteredCompanies = useMemo(() => {
    if (!search.trim()) return companies;
    const q = search.trim().toLowerCase();
    return companies.filter(([comp]) => comp.toLowerCase().includes(q));
  }, [companies, search]);

  const selectedCount = useMemo(() => {
    if (!value) return totalCount;
    const found = companies.find(([c]) => c.toLowerCase() === value.toLowerCase());
    return found ? found[1] : 0;
  }, [value, companies, totalCount]);

  const handleSelect = (comp: string) => {
    onChange(comp);
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
        aria-label="Filter applications by company"
      >
        <svg
          className={styles.icon}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
          <path d="M9 22v-4h6v4" />
          <path d="M8 6h.01" />
          <path d="M16 6h.01" />
          <path d="M8 10h.01" />
          <path d="M16 10h.01" />
          <path d="M8 14h.01" />
          <path d="M16 14h.01" />
        </svg>

        <span className={styles.label}>{value || "All Companies"}</span>

        <span className={styles.badge}>{selectedCount}</span>

        {value && (
          <button
            type="button"
            className={styles.clearBtn}
            onClick={handleClear}
            title="Clear company filter"
            aria-label="Clear company filter"
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
          {companies.length > 7 && (
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
                  placeholder="Filter companies…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className={styles.list}>
            {/* Option to select All Companies */}
            {(!search.trim() || "all companies".includes(search.toLowerCase().trim())) && (
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
                  All Companies
                </span>
                <span className={styles.itemCount}>{totalCount}</span>
              </button>
            )}

            {/* Individual company options */}
            {filteredCompanies.map(([comp, count]) => {
              const isSelected = value.toLowerCase() === comp.toLowerCase();
              return (
                <button
                  key={comp}
                  type="button"
                  className={`${styles.item} ${isSelected ? styles.itemActive : ""}`}
                  onClick={() => handleSelect(comp)}
                  role="option"
                  aria-selected={isSelected}
                >
                  <span className={styles.itemName}>
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
                    {comp}
                  </span>
                  <span className={styles.itemCount}>{count}</span>
                </button>
              );
            })}

            {filteredCompanies.length === 0 && search.trim() && (
              <div className={styles.emptyState}>No companies match &ldquo;{search}&rdquo;</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
