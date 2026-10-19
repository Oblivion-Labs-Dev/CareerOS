"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import styles from "./facet-filter-dropdown.module.css";

export interface FacetFilterDropdownProps {
  value: string;
  onChange: (val: string) => void;
  items: [string, number][]; // [itemName, count]
  totalCount: number;
  allLabel: string;
  searchPlaceholder: string;
  emptySearchLabel: string;
  icon: React.ReactNode;
  ariaLabel: string;
  clearTitle: string;
}

export function FacetFilterDropdown({
  value,
  onChange,
  items,
  totalCount,
  allLabel,
  searchPlaceholder,
  emptySearchLabel,
  icon,
  ariaLabel,
  clearTitle,
}: FacetFilterDropdownProps) {
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

  // Filter items in popup if user types in search box
  const filteredItems = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.trim().toLowerCase();
    return items.filter(([name]) => name.toLowerCase().includes(q));
  }, [items, search]);

  const selectedCount = useMemo(() => {
    if (!value) return totalCount;
    const found = items.find(([name]) => name.toLowerCase() === value.toLowerCase());
    return found ? found[1] : 0;
  }, [value, items, totalCount]);

  const handleSelect = (name: string) => {
    onChange(name);
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
        aria-label={ariaLabel}
      >
        {icon}

        <span className={styles.label}>{value || allLabel}</span>

        <span className={styles.badge}>{selectedCount}</span>

        {value && (
          <button
            type="button"
            className={styles.clearBtn}
            onClick={handleClear}
            title={clearTitle}
            aria-label={clearTitle}
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
          {items.length > 7 && (
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
                  placeholder={searchPlaceholder}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className={styles.list}>
            {/* Option to select All */}
            {(!search.trim() || allLabel.toLowerCase().includes(search.toLowerCase().trim())) && (
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
                  {allLabel}
                </span>
                <span className={styles.itemCount}>{totalCount}</span>
              </button>
            )}

            {/* Individual options */}
            {filteredItems.map(([name, count]) => {
              const isSelected = value.toLowerCase() === name.toLowerCase();
              return (
                <button
                  key={name}
                  type="button"
                  className={`${styles.item} ${isSelected ? styles.itemActive : ""}`}
                  onClick={() => handleSelect(name)}
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
                    {name}
                  </span>
                  <span className={styles.itemCount}>{count}</span>
                </button>
              );
            })}

            {filteredItems.length === 0 && search.trim() && (
              <div className={styles.emptyState}>
                {emptySearchLabel} &ldquo;{search}&rdquo;
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
