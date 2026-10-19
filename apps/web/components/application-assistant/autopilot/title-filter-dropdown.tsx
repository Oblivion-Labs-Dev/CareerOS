"use client";

import React from "react";
import { FacetFilterDropdown } from "./facet-filter-dropdown";

export interface TitleFilterDropdownProps {
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
      <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
      <path d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16" />
    </svg>
  );

  return (
    <FacetFilterDropdown
      value={value}
      onChange={onChange}
      items={titles}
      totalCount={totalCount}
      allLabel="All Titles"
      searchPlaceholder="Filter titles…"
      emptySearchLabel="No titles match"
      icon={icon}
      ariaLabel="Filter applications by job title"
      clearTitle="Clear title filter"
    />
  );
}
