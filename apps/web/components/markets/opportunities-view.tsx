"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getClientApiBaseUrl, postJson } from "@/lib/api";
import { enqueueJobForAutopilot } from "@/lib/application-assistant-api";
import { H1BMark } from "./bits";
import { shortDate } from "./format";
import type { LinkCheckProgress, MarketCompany, Opportunity } from "./types";
import styles from "./markets.module.css";

type Chip = "new" | "high" | "tier1" | "Agentic AI" | "AI/ML" | "Backend" | "Platform" | "Distributed Systems";
const CHIPS: { id: Chip; label: string }[] = [
  { id: "new", label: "New" },
  { id: "high", label: "80%+" },
  { id: "tier1", label: "Tier 1" },
  { id: "Agentic AI", label: "Agentic AI" },
  { id: "AI/ML", label: "AI/ML" },
  { id: "Backend", label: "Backend" },
  { id: "Platform", label: "Platform" },
  { id: "Distributed Systems", label: "Distributed Systems" },
];
const PAGE = 50;

type ActionState = { save?: "busy" | "done" | "error"; apply?: "busy" | "done" | "dup" | "filtered" | "error"; message?: string };

export function OpportunitiesView({
  marketId,
  marketName,
  linkCheck,
  onReload,
  refreshRunning,
  opportunities,
  companies,
  companyFilter,
  onCompanyFilter,
  onOpenCompany,
}: {
  marketId: string;
  marketName: string;
  linkCheck?: LinkCheckProgress;
  onReload: () => void | Promise<void>;
  refreshRunning: boolean;
  opportunities: Opportunity[];
  companies: MarketCompany[];
  companyFilter: string | null;
  onCompanyFilter: (id: string | null) => void;
  onOpenCompany: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [chips, setChips] = useState<Chip[]>([]);
  const [shown, setShown] = useState(PAGE);
  const [actions, setActions] = useState<Record<string, ActionState>>({});
  const [showBroken, setShowBroken] = useState(false);
  const [checking, setChecking] = useState<LinkCheckProgress | null>(linkCheck?.running ? linkCheck : null);
  const [checkError, setCheckError] = useState("");
  const companyName = companyFilter ? companies.find((c) => c.id === companyFilter)?.name : null;

  useEffect(() => {
    if (linkCheck?.running) setChecking(linkCheck);
  }, [linkCheck]);

  useEffect(() => {
    if (!checking?.running) return;
    const timer = window.setInterval(async () => {
      try {
        const res = await fetch(`${getClientApiBaseUrl()}/markets/${marketId}/links`, { credentials: "include", cache: "no-store" });
        const next = (await res.json()) as LinkCheckProgress;
        setChecking(next);
        if (!next.running) {
          if (next.error) setCheckError(next.error);
          void onReload();
        }
      } catch {
        /* the next tick retries */
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [checking?.running, marketId, onReload]);

  async function checkLinks() {
    setCheckError("");
    try {
      const res = await postJson<{ progress: LinkCheckProgress }>(`/markets/${marketId}/links/check`, {});
      setChecking({ ...res.progress, running: true });
    } catch (e) {
      setCheckError(e instanceof Error ? e.message : "Could not start the link check");
    }
  }

  const matched = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return opportunities.filter((o) => {
      if (companyFilter && o.companyId !== companyFilter) return false;
      if (needle && !`${o.title} ${o.company} ${o.areas.join(" ")}`.toLowerCase().includes(needle)) return false;
      for (const chip of chips) {
        if (chip === "new" && !o.isNew) return false;
        else if (chip === "high" && o.score < 80) return false;
        else if (chip === "tier1" && o.tier !== 1) return false;
        else if (chip !== "new" && chip !== "high" && chip !== "tier1" && !o.tags.includes(chip)) return false;
      }
      return true;
    });
  }, [opportunities, companyFilter, q, chips]);
  const brokenCount = matched.filter((o) => o.link?.status === "dead").length;
  const rows = showBroken ? matched : matched.filter((o) => o.link?.status !== "dead");
  const checkedCount = opportunities.filter((o) => o.link).length;

  const patch = (id: string, next: ActionState) => setActions((prev) => ({ ...prev, [id]: { ...prev[id], ...next } }));

  async function save(o: Opportunity) {
    patch(o.id, { save: "busy" });
    try {
      await postJson(`/jobs/discover/${encodeURIComponent(o.id)}/save`, {});
      patch(o.id, { save: "done", message: "Saved to tracker" });
    } catch (e) {
      patch(o.id, { save: "error", message: e instanceof Error ? e.message : "Save failed" });
    }
  }

  async function apply(o: Opportunity) {
    patch(o.id, { apply: "busy" });
    try {
      const res = (await enqueueJobForAutopilot({
        jobId: o.id,
        company: o.company,
        title: o.title,
        applicationUrl: o.applyUrl || o.url,
        location: o.location,
        matchScore: o.score,
        datePosted: o.postedAt,
      })) as { success: boolean; deduplicated?: boolean; filtered?: boolean; message?: string };
      if (res.filtered) patch(o.id, { apply: "filtered", message: res.message });
      else if (res.deduplicated) patch(o.id, { apply: "dup", message: res.message });
      else patch(o.id, { apply: res.success ? "done" : "error", message: res.success ? "Queued in Autopilot" : res.message });
    } catch (e) {
      patch(o.id, { apply: "error", message: e instanceof Error ? e.message : "Could not queue" });
    }
  }

  const toggle = (chip: Chip) => {
    setChips((prev) => (prev.includes(chip) ? prev.filter((c) => c !== chip) : [...prev, chip]));
    setShown(PAGE);
  };

  return (
    <>
      <div className={styles.oppHeader}>
        <span className={styles.oppTitle}>
          {rows.length} {companyName ? `${companyName} ` : `${marketName} `}opportunit{rows.length === 1 ? "y" : "ies"}
        </span>
        {companyName ? (
          <button type="button" className={styles.clear} onClick={() => onCompanyFilter(null)}>Show all companies</button>
        ) : null}
        <span className={styles.resultCount}>Senior software roles in the market, from every source, best match first</span>
      </div>
      <div className={styles.linkBar}>
        {checking?.running ? (
          <span>Checking job links… {checking.done ?? 0}/{checking.total ?? 0}{checking.dead ? `, ${checking.dead} broken so far` : ""}</span>
        ) : (
          <>
            <span>
              {checkedCount === 0
                ? "Job links have not been checked yet."
                : brokenCount
                  ? `${brokenCount} job${brokenCount === 1 ? "" : "s"} with a broken link ${showBroken ? "shown" : "hidden"}.`
                  : "Every checked job link opens."}
            </span>
            {brokenCount ? (
              <button type="button" className={styles.clear} onClick={() => setShowBroken((v) => !v)}>{showBroken ? "Hide them" : "Show them"}</button>
            ) : null}
            <button type="button" className={styles.clear} onClick={checkLinks} disabled={refreshRunning}
              title={refreshRunning ? "Links are checked when the market refresh finishes" : "Open every job link and hide the ones that no longer work"}>
              Check links
            </button>
          </>
        )}
        {checkError ? <span className={styles.linkError}>{checkError}</span> : null}
      </div>
      <div className={styles.controls}>
        <input
          className={styles.search}
          type="search"
          placeholder="Search titles, companies, areas…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setShown(PAGE); }}
          aria-label="Search opportunities"
        />
        <div className={styles.chips}>
          {CHIPS.map((chip) => (
            <button key={chip.id} type="button" className={styles.chip} aria-pressed={chips.includes(chip.id)} onClick={() => toggle(chip.id)}>
              {chip.label}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.oppList}>
        {rows.length === 0 ? (
          <div className={styles.empty}>
            {opportunities.length === 0 ? (
              <>
                <strong>No opportunities yet</strong>
                <p>Run a market refresh to read every tracked company&apos;s career site. Jobs already found by Browse Jobs will appear here too.</p>
              </>
            ) : (
              <>
                <strong>Nothing matches these filters</strong>
                <p>{opportunities.length} opportunities are hidden by the current filters.</p>
                <button type="button" className="btn btn-sm" onClick={() => { setChips([]); setQ(""); onCompanyFilter(null); }}>Clear filters</button>
              </>
            )}
          </div>
        ) : (
          rows.slice(0, shown).map((o) => {
            const state = actions[o.id] ?? {};
            const dead = o.link?.status === "dead";
            const deadWhy = dead ? `This job link no longer works (${o.link?.reason}).` : undefined;
            return (
              <div key={o.id} className={styles.oppRow}>
                <span className={styles.score} data-band={o.score >= 80 ? "high" : o.score >= 60 ? "mid" : undefined}>{o.score}</span>
                <div className={styles.oppMain}>
                  <div className={styles.oppJob}>
                    {dead ? <span title={deadWhy}>{o.title}</span> : <a href={o.url} target="_blank" rel="noreferrer">{o.title}</a>}
                    {o.isNew ? <span className={styles.newBadge}>NEW</span> : null}
                  </div>
                  {o.tags.length || state.message || dead ? (
                    <div className={styles.tags}>
                      {dead ? <span className={styles.tag} data-tone="warn" title={deadWhy}>Link broken</span> : null}
                      {o.tags.map((t) => <span key={t} className={styles.tag}>{t}</span>)}
                      {state.message ? <span className={styles.oppSourceTag}>{state.message}</span> : null}
                    </div>
                  ) : null}
                </div>
                <div className={styles.oppCompany}>
                  <span>
                    <button type="button" className={styles.clear} style={{ color: "var(--text-secondary)" }} onClick={() => onOpenCompany(o.companyId)}>
                      {o.company}
                    </button>
                    {o.tier ? <span className={styles.oppSourceTag}> · T{o.tier}</span> : null}
                  </span>
                  <span className={styles.oppSourceTag}>{o.official ? "Official posting" : o.source ?? "Other source"}</span>
                </div>
                <div className={`${styles.oppCompany} ${styles.oppArea}`}>
                  <span>{o.areas.slice(0, 2).join(", ") || o.location}</span>
                  <span className={styles.oppSourceTag}>{o.zone ? `Zone ${o.zone}` : ""}</span>
                </div>
                <div className={styles.oppH1b}><H1BMark strength={o.h1b} /></div>
                <span className={`${styles.oppSourceTag} ${styles.oppPosted}`}>{shortDate(o.postedAt ?? o.firstSeenAt)}</span>
                <div className={styles.oppActions}>
                  {dead ? (
                    <button type="button" className={styles.mini} disabled title={deadWhy}>View</button>
                  ) : (
                    <a className={styles.mini} href={o.url} target="_blank" rel="noreferrer">View</a>
                  )}
                  <Link className={styles.mini} href={`/profile/resume-studio?job=${encodeURIComponent(o.id)}`} title="Build a resume for this job in Resume Studio">
                    Resume
                  </Link>
                  <button type="button" className={styles.mini} data-done={state.save === "done"} disabled={state.save === "busy" || state.save === "done"} onClick={() => save(o)}>
                    {state.save === "done" ? "Saved" : state.save === "busy" ? "Saving…" : "Save"}
                  </button>
                  <button
                    type="button"
                    className={`${styles.mini} ${styles.miniPrimary}`}
                    data-done={state.apply === "done" || state.apply === "dup"}
                    data-tone={state.apply === "filtered" || state.apply === "error" ? "warn" : undefined}
                    disabled={dead || state.apply === "busy" || state.apply === "done" || state.apply === "dup"}
                    onClick={() => apply(o)}
                    title={deadWhy ?? "Queue in Autopilot. Hard filters and Tier-1 guardrails still apply."}
                  >
                    {state.apply === "done" ? "Queued" : state.apply === "dup" ? "In queue" : state.apply === "busy" ? "Queuing…" : state.apply === "filtered" ? "Filtered" : "Apply"}
                  </button>
                </div>
              </div>
            );
          })
        )}
        {rows.length > shown ? (
          <div className={styles.more}>
            <button type="button" className="btn btn-sm" onClick={() => setShown((n) => n + PAGE)}>Show {Math.min(PAGE, rows.length - shown)} more</button>
          </div>
        ) : null}
      </div>
    </>
  );
}
