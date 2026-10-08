"use client";

import { useMemo, useState } from "react";
import { H1BMark, SourceTip, StatusDot, Tip, statusText } from "./bits";
import { hostOf, priorityLabel, timeAgo } from "./format";
import type { H1BStrength, MarketCompany, StatusBucket } from "./types";
import styles from "./markets.module.css";

type SortKey = "priority" | "name" | "h1b" | "opportunities" | "scan";
type Chip = "tier1" | "h1bStrong" | "hiring" | "newJobs" | "manual";

const H1B_RANK: Record<H1BStrength, number> = { strong: 0, moderate: 1, weak: 2 };
const CHIPS: { id: Chip; label: string; tone?: "warn" }[] = [
  { id: "tier1", label: "Tier 1" },
  { id: "h1bStrong", label: "H1B Strong" },
  { id: "hiring", label: "Hiring Now" },
  { id: "newJobs", label: "New Jobs" },
  { id: "manual", label: "Manual", tone: "warn" },
];

export interface CompanyFilters {
  q: string;
  tier: string;
  h1b: string;
  area: string;
  source: string;
  status: string;
  hiring: string;
  chips: Chip[];
}

export const EMPTY_FILTERS: CompanyFilters = { q: "", tier: "", h1b: "", area: "", source: "", status: "", hiring: "", chips: [] };

function matches(c: MarketCompany, f: CompanyFilters): boolean {
  if (f.q) {
    const q = f.q.toLowerCase();
    const hay = `${c.name} ${c.category ?? ""} ${c.areas.join(" ")} ${c.career.label}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  if (f.tier && String(c.tier) !== f.tier) return false;
  if (f.h1b && c.h1b.strength !== f.h1b) return false;
  if (f.area && !c.areas.includes(f.area)) return false;
  if (f.source && c.career.label !== f.source) return false;
  if (f.status && c.career.status !== f.status) return false;
  if (f.hiring === "yes" && c.jobs.relevant === 0) return false;
  if (f.hiring === "no" && c.jobs.relevant > 0) return false;
  for (const chip of f.chips) {
    if (chip === "tier1" && c.tier !== 1) return false;
    if (chip === "h1bStrong" && c.h1b.strength !== "strong") return false;
    if (chip === "hiring" && c.jobs.relevant === 0) return false;
    if (chip === "newJobs" && c.jobs.newCount === 0) return false;
    if (chip === "manual" && c.career.status !== "manual") return false;
  }
  return true;
}

function sorter(key: SortKey): (a: MarketCompany, b: MarketCompany) => number {
  const byPriority = (a: MarketCompany, b: MarketCompany) => (a.priority ?? 9999) - (b.priority ?? 9999);
  switch (key) {
    case "name":
      return (a, b) => a.name.localeCompare(b.name);
    case "h1b":
      return (a, b) => H1B_RANK[a.h1b.strength] - H1B_RANK[b.h1b.strength] || byPriority(a, b);
    case "opportunities":
      return (a, b) => b.jobs.relevant - a.jobs.relevant || b.jobs.highMatch - a.jobs.highMatch || byPriority(a, b);
    case "scan":
      return (a, b) => (b.career.lastSuccessAt ?? "").localeCompare(a.career.lastSuccessAt ?? "") || byPriority(a, b);
    default:
      return byPriority;
  }
}

function OpportunityCell({ c }: { c: MarketCompany }) {
  const j = c.jobs;
  if (j.relevant > 0) {
    const parts = [j.newCount ? `${j.newCount} new` : "", j.highMatch ? `${j.highMatch} ≥80%` : ""].filter(Boolean);
    const viaOthers = j.state !== "known" && j.otherSources > 0;
    return (
      <div className={styles.opps}>
        <div className={styles.oppsMain}><b>{j.relevant}</b>relevant</div>
        <div className={styles.oppsSub}>
          {parts.length ? <span className={j.newCount ? styles.oppsNew : undefined}>{parts.join(" · ")}</span> : null}
          {viaOthers ? <span>{parts.length ? " · " : ""}via other sources</span> : null}
          {!parts.length && !viaOthers && j.inMarket != null ? <span>{j.inMarket} jobs in area</span> : null}
        </div>
      </div>
    );
  }
  if (j.state === "known") {
    return (
      <div className={styles.opps}>
        <div className={`${styles.oppsMain} ${styles.oppsMuted}`}>0 matches</div>
        <div className={styles.oppsSub}>
          {j.inMarket ?? 0} in area · {j.totalOpen ?? 0} {j.scope === "search" ? "searched" : "scanned"}
        </div>
      </div>
    );
  }
  if (j.state === "pending") {
    return (
      <div className={styles.opps}>
        <div className={`${styles.oppsMain} ${styles.oppsMuted}`}>Not scanned yet</div>
        <div className={styles.oppsSub}>Auto-searchable</div>
      </div>
    );
  }
  return (
    <div className={styles.opps}>
      <div className={`${styles.oppsMain} ${styles.oppsManual}`}>Unknown</div>
      <div className={styles.oppsSub}>Manual search required</div>
    </div>
  );
}

export function CompanyTable({
  companies,
  selectedId,
  onSelect,
  filters,
  onFilters,
}: {
  companies: MarketCompany[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  filters: CompanyFilters;
  onFilters: (next: CompanyFilters) => void;
}) {
  const [sort, setSort] = useState<SortKey>("priority");
  const areas = useMemo(() => [...new Set(companies.flatMap((c) => c.areas))].sort(), [companies]);
  const sources = useMemo(() => [...new Set(companies.map((c) => c.career.label))].sort(), [companies]);
  const rows = useMemo(() => companies.filter((c) => matches(c, filters)).sort(sorter(sort)), [companies, filters, sort]);
  const active = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS);

  const set = (patch: Partial<CompanyFilters>) => onFilters({ ...filters, ...patch });
  const toggleChip = (chip: Chip) =>
    set({ chips: filters.chips.includes(chip) ? filters.chips.filter((c) => c !== chip) : [...filters.chips, chip] });

  const sortHead = (key: SortKey, label: string) => (
    <button type="button" className={styles.sortBtn} data-active={sort === key} onClick={() => setSort(key)}>
      {label}{sort === key ? " ↓" : ""}
    </button>
  );

  const select = (value: string, onChange: (v: string) => void, label: string, options: [string, string][]) => (
    <select className={styles.filter} data-active={Boolean(value)} value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
      <option value="">{label}</option>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );

  return (
    <>
      <div className={styles.controls}>
        <input
          className={styles.search}
          type="search"
          placeholder="Search companies, categories, areas…"
          value={filters.q}
          onChange={(e) => set({ q: e.target.value })}
          aria-label="Search companies"
        />
        {select(filters.tier, (v) => set({ tier: v }), "Tier", [["1", "Tier 1"], ["2", "Tier 2"], ["3", "Tier 3"], ["4", "Tier 4"]])}
        {select(filters.h1b, (v) => set({ h1b: v }), "H1B", [["strong", "Strong"], ["moderate", "Moderate"], ["weak", "Unknown"]])}
        {select(filters.area, (v) => set({ area: v }), "Area", areas.map((a) => [a, a]))}
        {select(filters.source, (v) => set({ source: v }), "Source", sources.map((s) => [s, s]))}
        {select(filters.status, (v) => set({ status: v }), "Status", [["healthy", "Healthy"], ["manual", "Manual"], ["degraded", "Degraded"], ["failed", "Failed"], ["pending", "Not scanned"]])}
        {select(filters.hiring, (v) => set({ hiring: v }), "Hiring", [["yes", "Hiring"], ["no", "No matches"]])}
      </div>
      <div className={styles.controls}>
        <div className={styles.chips}>
          {CHIPS.map((chip) => (
            <button
              key={chip.id}
              type="button"
              className={styles.chip}
              data-tone={chip.tone}
              aria-pressed={filters.chips.includes(chip.id)}
              onClick={() => toggleChip(chip.id)}
            >
              {chip.label}
            </button>
          ))}
        </div>
        <span className={styles.resultCount}>
          {rows.length === companies.length ? `${companies.length} companies` : `${rows.length} of ${companies.length}`}
          {active ? <> · <button type="button" className={styles.clear} onClick={() => onFilters(EMPTY_FILTERS)}>Clear filters</button></> : null}
        </span>
      </div>

      <div className={styles.table} role="table" aria-label="Tracked companies">
        <div className={styles.thead} role="row">
          <span>{sortHead("priority", "#")}</span>
          <span>{sortHead("name", "Company")}</span>
          <span className={styles.colArea}>Area</span>
          <span className={styles.colH1b}>{sortHead("h1b", "H1B")}</span>
          <span className={styles.colSource}>Source</span>
          <span>{sortHead("opportunities", "Opportunities")}</span>
          <span>{sortHead("scan", "Status")}</span>
        </div>
        {rows.length === 0 ? (
          <div className={styles.empty}>
            <strong>No companies match these filters</strong>
            <p>Loosen a filter or clear them to see all {companies.length} tracked companies.</p>
            <button type="button" className="btn btn-sm" onClick={() => onFilters(EMPTY_FILTERS)}>Clear filters</button>
          </div>
        ) : (
          rows.map((c) => <CompanyRow key={c.id} c={c} selected={c.id === selectedId} onSelect={onSelect} />)
        )}
      </div>
    </>
  );
}

function CompanyRow({ c, selected, onSelect }: { c: MarketCompany; selected: boolean; onSelect: (id: string) => void }) {
  const status: StatusBucket = c.career.status;
  const ago = c.career.lastSuccessAt ?? c.career.lastAttemptAt;
  const sub = c.career.url ? hostOf(c.career.url) : c.career.failureReason || "No career URL";
  return (
    <div
      role="row"
      tabIndex={0}
      className={styles.row}
      data-selected={selected}
      onClick={() => onSelect(c.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(c.id);
        }
      }}
    >
      <span className={styles.rank}>{priorityLabel(c.priority)}</span>
      <div className={styles.companyCell}>
        <div className={styles.companyName}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{c.name}</span>
          {c.tier ? <span className={styles.tier} data-tier={c.tier}>T{c.tier}</span> : null}
        </div>
        <div className={styles.companySub}>{c.category || c.localPresence || "—"}</div>
      </div>
      <div className={`${styles.areaCell} ${styles.colArea}`}>
        <span>{c.areas.slice(0, 2).join(", ") || "—"}</span>
        <span className={styles.zone}>{c.zone ? `Zone ${c.zone}` : ""}</span>
      </div>
      <div className={styles.colH1b}><H1BMark strength={c.h1b.strength} h1b={c.h1b} /></div>
      <div className={styles.colSource}>
        <Tip className={styles.source} body={<SourceTip company={c} />}>
          <span>{c.career.label}</span>
          <span className={styles.sourceMethod}>{sub}</span>
        </Tip>
      </div>
      <OpportunityCell c={c} />
      <div>
        <span className={styles.status}><StatusDot status={status} />{statusText(status, c.career.sourceType)}</span>
        <span className={styles.statusAgo}>{ago ? timeAgo(ago) : "never scanned"}</span>
      </div>
    </div>
  );
}
