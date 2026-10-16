"use client";

import React from "react";
import { FacetFilterDropdown } from "./facet-filter-dropdown";

export interface CompanyFilterDropdownProps {
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
  const icon = (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ width: "0.95rem", height: "0.95rem", color: "var(--muted, #9496a1)", flexShrink: 0 }}
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
  );

  return (
    <FacetFilterDropdown
      value={value}
      onChange={onChange}
      items={companies}
      totalCount={totalCount}
      allLabel="All Companies"
      searchPlaceholder="Filter companies…"
      emptySearchLabel="No companies match"
      icon={icon}
      ariaLabel="Filter applications by company"
      clearTitle="Clear company filter"
    />
  );
}
