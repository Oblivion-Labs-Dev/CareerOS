"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CareerIcon } from "@/components/ui/career-icon";
import { getClientApiBaseUrl, postJson } from "@/lib/api";
import { CompanyDrawer } from "./company-drawer";
import { CompanyTable, EMPTY_FILTERS, type CompanyFilters } from "./company-table";
import { StatusDot } from "./bits";
import { plural, timeAgo } from "./format";
import { OpportunitiesView } from "./opportunities-view";
import { SourceHealth } from "./source-health";
import type { MarketOverview, RefreshProgress, RunSummary, StatusBucket } from "./types";
import styles from "./markets.module.css";

type Tab = "companies" | "opportunities" | "health";
const TABS: { id: Tab; label: string }[] = [
  { id: "companies", label: "Companies" },
  { id: "opportunities", label: "Opportunities" },
  { id: "health", label: "Source Health" },
];
const POLL_MS = 1500;
const RELOAD_EVERY = 4;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${getClientApiBaseUrl()}${path}`, { credentials: "include", cache: "no-store" });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

function ProgressStrip({ progress, onHide }: { progress: RefreshProgress; onHide: () => void }) {
  const groups = Object.entries(progress.groups ?? {}).filter(([, g]) => g.total > 0);
  const detecting = progress.phase === "detecting" || progress.phase === "starting";
  const det = progress.groups?.detect;
  const done = detecting ? det?.done ?? progress.counts?.detected ?? 0 : progress.done ?? 0;
  const total = detecting ? det?.total || progress.total || 0 : progress.total ?? 0;
  const pct = total ? Math.min(100, (100 * done) / total) : 4;
  const label = detecting
    ? `Detecting career sources ${done} / ${total}`
    : progress.phase === "importing"
      ? "Importing jobs…"
      : `Scanning ${done} / ${total}`;
  return (
    <div className={styles.progress} role="status" aria-live="polite">
      <span className={styles.progressLabel}>{label}</span>
      <div className={styles.progressTrack}><div className={styles.progressFill} style={{ width: `${pct}%` }} /></div>
      <button type="button" className={styles.dismiss} onClick={onHide}>Run in background</button>
      {groups.length ? (
        <div className={styles.progressGroups}>
          {groups.map(([key, g]) => (
            <span key={key} data-done={g.done >= g.total} data-active={g.done > 0 && g.done < g.total}>
              {g.label} {g.done}/{g.total}
            </span>
          ))}
          {progress.counts?.imported ? <span>{progress.counts.imported} jobs imported</span> : null}
        </div>
      ) : null}
      {progress.current?.length ? <div className={styles.progressCurrent}>Now: {progress.current.join(" · ")}</div> : null}
    </div>
  );
}

function FinishedStrip({ summary, onDismiss }: { summary: RunSummary; onDismiss: () => void }) {
  return (
    <div className={styles.finished} role="status">
      <strong>Scan finished</strong>
      <span>{plural(summary.scanned, "company", "companies")} read{summary.skipped ? `, ${summary.skipped} fresh skipped` : ""}</span>
      <span className={styles.plus}>+{summary.newJobs} new</span>
      <span className={styles.minus}>−{summary.closedJobs} expired</span>
      {summary.sourceChanges.length ? <span>{plural(summary.sourceChanges.length, "source")} changed</span> : null}
      {summary.needsAttention ? <span className={styles.warn}>{summary.needsAttention} need attention</span> : null}
      <button type="button" className={styles.dismiss} onClick={onDismiss}>Dismiss</button>
    </div>
  );
}

function Changes({ run, runs }: { run: RunSummary; runs: RunSummary[] }) {
  const baseline = runs.length <= 1 && run.newJobs === 0 && run.closedJobs === 0;
  const parts: string[] = [];
  if (run.newJobs) parts.push(`+${run.newJobs} new relevant`);
  if (run.closedJobs) parts.push(`−${run.closedJobs} closed`);
  if (run.startedHiring.length) parts.push(`${run.startedHiring.slice(0, 3).join(", ")} started hiring`);
  if (run.stoppedHiring.length) parts.push(`${plural(run.stoppedHiring.length, "company", "companies")} stopped hiring`);
  if (run.sourceChanges.length) parts.push(run.sourceChanges.map((c) => `${c.company}: ${c.from} → ${c.to}`).slice(0, 2).join("; "));
  return (
    <div className={styles.meta} style={{ marginTop: 0 }}>
      <b>Changes since last scan:</b>
      <span>{baseline ? "first scan, baseline recorded" : parts.length ? parts.join(" · ") : "no changes"}</span>
      <span>· {timeAgo(run.finishedAt)}</span>
    </div>
  );
}

export function MarketsDashboard({ marketId = "seattle" }: { marketId?: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const tab = (params.get("tab") as Tab) || "companies";
  const selectedId = params.get("company");
  const jobsCompany = params.get("jobsCompany");

  const [data, setData] = useState<MarketOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<RefreshProgress | null>(null);
  const [stripHidden, setStripHidden] = useState(false);
  const [finished, setFinished] = useState<RunSummary | null>(null);
  const [refreshingIds, setRefreshingIds] = useState<Set<string>>(new Set());
  const [filters, setFilters] = useState<CompanyFilters>(EMPTY_FILTERS);
  const [importing, setImporting] = useState(false);
  const pollTick = useRef(0);

  const setParams = useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v == null) next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  const load = useCallback(async () => {
    try {
      const overview = await getJson<MarketOverview>(`/markets/${marketId}`);
      setData(overview);
      setError(null);
      if (overview.refresh?.running) setProgress(overview.refresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the market");
    }
  }, [marketId]);

  useEffect(() => { void load(); }, [load]);

  const running = Boolean(progress?.running);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getJson<RefreshProgress>(`/markets/${marketId}/refresh`);
        setProgress(next);
        pollTick.current += 1;
        if (!next.running) {
          if (next.summary) setFinished(next.summary);
          setStripHidden(false);
          void load();
        } else if (pollTick.current % RELOAD_EVERY === 0) {
          void load();
        }
      } catch {
        /* transient; keep polling */
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [running, marketId, load]);

  async function refreshMarket(force = false) {
    setFinished(null);
    setStripHidden(false);
    try {
      const started = await postJson<RefreshProgress>(`/markets/${marketId}/refresh`, { force, allowBrowser: true });
      setProgress({ ...started, running: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed to start");
    }
  }

  async function refreshCompany(id: string) {
    setRefreshingIds((s) => new Set(s).add(id));
    try {
      await postJson(`/markets/${marketId}/companies/${id}/refresh`, {});
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Company refresh failed");
    } finally {
      setRefreshingIds((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }
  }

  async function importSeed() {
    setImporting(true);
    try {
      await postJson(`/markets/${marketId}/import`, {});
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  const selected = useMemo(() => data?.companies.find((c) => c.id === selectedId) ?? null, [data, selectedId]);
  const tier1Total = useMemo(() => data?.companies.filter((c) => c.tier === 1).length ?? 0, [data]);

  if (error && !data) {
    return (
      <div className={styles.page}>
        <div className={styles.error}>Markets could not load: {error}. Check that the API is running, then reload.</div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className={styles.page}>
        <div className={styles.header}><div className={styles.headerCopy}><div className={styles.title}>Markets</div><div className={styles.subtitle}>Loading market…</div></div></div>
        <div className={styles.table}>{Array.from({ length: 8 }, (_, i) => <div key={i} className={styles.skeleton} />)}</div>
      </div>
    );
  }

  const { market, pulse, strip, companies, opportunities, health } = data;
  const neverScanned = !pulse.lastRun && companies.every((c) => !c.career.lastAttemptAt);
  const showHealth = (status: StatusBucket) => {
    setFilters({ ...EMPTY_FILTERS, status });
    setParams({ tab: null });
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerCopy}>
          <div className={styles.titleRow}>
            <h1 className={styles.title}>{market.name}</h1>
          </div>
          <div className={styles.subtitle}>{market.tagline || `${market.origin}-centered opportunity radar`}</div>
          <div className={styles.meta}>
            <span>{pulse.lastScanAt ? <>Last scan <b>{timeAgo(pulse.lastScanAt)}</b></> : "Never scanned"}</span>
            <span>·</span>
            <span><b>{pulse.companies}</b> companies tracked</span>
            <span>·</span>
            <span>Origin {market.origin}</span>
          </div>
        </div>
        <div className={styles.headerRight}>
          <select className={styles.marketSelect} value={market.id} aria-label="Market" onChange={() => undefined}>
            <option value={market.id}>{market.name}</option>
          </select>
          <button
            type="button"
            className={`btn btn-sm ${styles.refreshBtn}`}
            data-running={running}
            disabled={running || companies.length === 0}
            onClick={() => refreshMarket(false)}
            title="Reads every company not scanned in the last few hours"
          >
            <span className={styles.spin}>↻</span>
            {running
              ? progress?.phase === "detecting" || progress?.phase === "starting"
                ? `Detecting ${progress?.groups?.detect?.done ?? 0} / ${progress?.groups?.detect?.total ?? 0}`
                : `Scanning ${progress?.done ?? 0} / ${progress?.total ?? 0}`
              : "Refresh Market"}
          </button>
        </div>
      </header>

      {error ? <div className={styles.error}>{error}</div> : null}
      {running && progress && !stripHidden ? <ProgressStrip progress={progress} onHide={() => setStripHidden(true)} /> : null}
      {!running && finished ? <FinishedStrip summary={finished} onDismiss={() => setFinished(null)} /> : null}

      {companies.length === 0 ? (
        <div className={styles.table}>
          <div className={styles.empty}>
            <strong>No companies tracked in {market.name} yet</strong>
            <p>Import the market&apos;s seed list to start tracking its companies, their career sites and H1B history.</p>
            <button type="button" className="btn btn-sm" disabled={importing} onClick={importSeed}>{importing ? "Importing…" : "Import seed list"}</button>
          </div>
        </div>
      ) : (
        <>
          <section className={styles.pulse} aria-label="Market pulse">
            <div className={styles.stat}>
              <div className={styles.statLabel}>Companies</div>
              <div className={styles.statValue}>{pulse.companies}</div>
              <div className={styles.statHint}>{pulse.hiringCompanies} hiring for your roles</div>
            </div>
            <div className={`${styles.stat} ${styles.statPrimary}`}>
              <div className={styles.statLabel}>Matches</div>
              <div className={styles.statValue}>{pulse.matches}</div>
              <div className={styles.statHint}>{pulse.highMatch} at 80%+</div>
            </div>
            <div className={styles.stat}>
              <div className={styles.statLabel}>Tier-1 hiring</div>
              <div className={styles.statValue}>{pulse.tier1Hiring}</div>
              <div className={styles.statHint}>of {tier1Total} tier-1 companies</div>
            </div>
            <div className={styles.stat}>
              <div className={styles.statLabel}>New this week</div>
              <div className={styles.statValue}>{pulse.newThisWeek}</div>
              <div className={styles.statHint}>first seen in 7 days</div>
            </div>
            <div className={styles.bars}>
              <div className={styles.bar}>
                <span>Auto-searchable</span><b>{pulse.autoSearchablePct}%</b>
                <div className={styles.barTrack}><div className={styles.barFill} style={{ width: `${pulse.autoSearchablePct}%` }} /></div>
              </div>
              <div className={styles.bar}>
                <span>Scanned in last 24h</span><b>{pulse.fresh24hPct}%</b>
                <div className={styles.barTrack}><div className={styles.barFill} data-tone={pulse.fresh24hPct < 50 ? "warn" : undefined} style={{ width: `${pulse.fresh24hPct}%` }} /></div>
              </div>
            </div>
            <div className={styles.healthCounts}>
              {(["healthy", "manual", "degraded", "failed"] as StatusBucket[]).map((s) => (
                <button key={s} type="button" className={styles.healthCount} onClick={() => showHealth(s)}>
                  <StatusDot status={s} />{s[0].toUpperCase() + s.slice(1)}<b>{pulse.health[s] ?? 0}</b>
                </button>
              ))}
              {pulse.health.pending ? (
                <button type="button" className={styles.healthCount} onClick={() => showHealth("pending")}>
                  <StatusDot status="pending" />Not scanned<b>{pulse.health.pending}</b>
                </button>
              ) : null}
            </div>
          </section>

          {neverScanned && !running ? (
            <div className={styles.strip} data-kind="new">
              <span className={styles.stripIcon}><CareerIcon name="radar" /></span>
              <span>{companies.length} companies imported. Run the first scan to read their career sites. Cheap APIs go first, then the heavier sites.</span>
              <button type="button" className={`btn btn-sm ${styles.stripAction}`} onClick={() => refreshMarket(false)}>Run first scan</button>
            </div>
          ) : strip && strip.kind !== "none" ? (
            <div className={styles.strip} data-kind={strip.kind}>
              <span className={styles.stripIcon}><CareerIcon name="spark" /></span>
              <span>{strip.text}</span>
              <button type="button" className={`btn btn-sm ${styles.stripAction}`} onClick={() => setParams({ tab: "opportunities", jobsCompany: null })}>Review</button>
            </div>
          ) : null}

          {pulse.lastRun ? <Changes run={pulse.lastRun} runs={data.runs} /> : null}

          <div className={styles.tabs} role="tablist">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                className={styles.tab}
                aria-selected={tab === t.id}
                onClick={() => setParams({ tab: t.id === "companies" ? null : t.id, jobsCompany: null })}
              >
                {t.label}
                <span className={styles.tabCount}>
                  {t.id === "companies" ? companies.length : t.id === "opportunities" ? opportunities.length : health.needsAttention.length}
                </span>
              </button>
            ))}
          </div>

          {tab === "opportunities" ? (
            <OpportunitiesView
              marketId={marketId}
              marketName={market.name}
              linkCheck={data.links}
              onReload={load}
              refreshRunning={running}
              opportunities={opportunities}
              companies={companies}
              companyFilter={jobsCompany}
              onCompanyFilter={(id) => setParams({ jobsCompany: id })}
              onOpenCompany={(id) => setParams({ company: id })}
            />
          ) : tab === "health" ? (
            <SourceHealth
              health={health}
              pulse={pulse}
              refreshingIds={refreshingIds}
              marketRunning={running}
              onRetry={refreshCompany}
              onOpenCompany={(id) => setParams({ company: id })}
            />
          ) : (
            <CompanyTable
              companies={companies}
              selectedId={selectedId}
              onSelect={(id) => setParams({ company: id })}
              filters={filters}
              onFilters={setFilters}
            />
          )}
        </>
      )}

      {selected ? (
        <CompanyDrawer
          marketId={marketId}
          company={selected}
          refreshing={refreshingIds.has(selected.id)}
          marketRunning={running}
          onClose={() => setParams({ company: null })}
          onRefresh={refreshCompany}
          onViewJobs={(id) => setParams({ tab: "opportunities", jobsCompany: id, company: null })}
        />
      ) : null}
    </div>
  );
}
