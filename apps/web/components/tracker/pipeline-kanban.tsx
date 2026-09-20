"use client";

import { useSessionState } from "@/hooks/use-session-state";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import styles from "./tracker-workspace.module.css";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  downloadApplicationsCsv,
  getTrackerPipeline,
  importApplicationsCsv,
  type PipelineColumn,
  type PipelineResponse,
} from "@/lib/tracker-api";

function timeAgo(days: number | null): string {
  if (days === null) return "—";
  if (days <= 0) return "today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

export function PipelineKanban() {
  const [search, setSearch] = useSessionState("pipeline-search", "");
  const [stage, setStage] = useSessionState("pipeline-stage", "all");
  const [view, setView] = useSessionState<"board" | "list">("pipeline-view", "board");
  const [mobile, setMobile] = useState(false);
  const touchStart = useRef<number | null>(null);
  useEffect(() => {
    const media = matchMedia("(max-width: 600px)");
    const update = () => setMobile(media.matches);
    update(); media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const lastStages = useRef<Map<string, string> | null>(null);
  const [changedIds, setChangedIds] = useState<Set<string>>(new Set());
  const [data, setData] = useState<PipelineResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const result = await getTrackerPipeline();
      const nextStages = new Map(result.columns.flatMap(column => column.items.map(item => [item.id,item.status] as const)));
      setChangedIds(new Set([...nextStages].filter(([id,status]) => lastStages.current?.has(id) && lastStages.current.get(id) !== status).map(([id]) => id)));
      lastStages.current = nextStages;
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the pipeline.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleImportClick = () => fileInputRef.current?.click();

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setImportBusy(true);
    setImportMessage(null);
    try {
      const result = await importApplicationsCsv(file);
      setImportMessage(`Imported: ${result.created} added, ${result.updated} updated, ${result.skipped} skipped.`);
      await load();
    } catch (err) {
      setImportMessage(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setImportBusy(false);
    }
  };

  const effectiveStage = mobile && stage === "all" ? data?.columns[0]?.key : stage;
  const columns = (data?.columns || []).filter(column => effectiveStage === "all" || column.key === effectiveStage).map(column => ({...column, items: column.items.filter(item => `${item.companyName} ${item.roleTitle}`.toLowerCase().includes(search.trim().toLowerCase()))}));
  return <div className={styles.workspace}>
    <div className={styles.toolbar}><div><h1>Pipeline</h1></div><div className={styles.actions}><input ref={fileInputRef} type="file" accept=".csv,text/csv" hidden onChange={handleFileChange} /><button onClick={handleImportClick} disabled={importBusy}>{importBusy ? 'Importing…' : 'Import CSV'}</button><button onClick={() => void downloadApplicationsCsv().catch(err => setImportMessage(err instanceof Error ? err.message : 'Export failed'))}>Export CSV ↗</button><button onClick={() => void load()}>Refresh ↻</button></div></div>
    {error && <p role="alert" className={styles.error}>{error}<button onClick={() => void load()}>Try again</button></p>}
    {importMessage && <p role="status" className={styles.caption}>{importMessage}</p>}
    {loading ? <WorkspaceLoading label="Loading pipeline…" shape="grid" rows={4} /> : data && <>
      <div className={styles.pipelineSummary}><div className={styles.total}><span>TRACKED OPPORTUNITIES</span><strong>{data.total}</strong><small>Your complete pipeline</small></div><div className={styles.distribution}><h3>Where things stand</h3><div className={styles.segmented} role="img" aria-label={data.columns.map(column => `${column.label}: ${column.items.length}`).join(', ')}>{data.columns.map(column => <span key={column.key} data-stage={column.key} style={{flex:column.items.length}} title={`${column.label}: ${column.items.length}`} />)}</div><div className={styles.legend}>{data.columns.map(column => <span key={column.key}><i data-stage={column.key} />{column.label} <b>{column.items.length}</b></span>)}</div><p className={styles.caption}>Ghosted flags {data.ghostThresholdDays}+ days since recorded activity; email replies may not be linked yet.</p></div></div>
      <div className={styles.boardControls}>
        <label className={styles.search}>Find an opportunity<input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search company or role…" /></label>
        <div className={styles.viewSwitch} aria-label="Pipeline view"><button aria-pressed={view === "board"} onClick={() => setView("board")}>Board</button><button aria-pressed={view === "list"} onClick={() => setView("list")}>List</button></div>
      </div>
      <nav className={styles.stageTabs} aria-label="Pipeline stages">{!mobile && <button aria-pressed={stage === "all"} onClick={() => setStage("all")}>All stages</button>}{data.columns.map(column => <button key={column.key} aria-pressed={effectiveStage === column.key} onClick={() => setStage(column.key)}>{column.label} <b>{column.items.length}</b></button>)}</nav>
      <div className={styles.board} data-view={view} onTouchStart={event => {touchStart.current = event.touches[0]?.clientX ?? null;}} onTouchEnd={event => {
        if (!mobile || touchStart.current === null) return;
        const distance = (event.changedTouches[0]?.clientX ?? touchStart.current) - touchStart.current;
        touchStart.current = null;
        if (Math.abs(distance) < 70) return;
        const index = data.columns.findIndex(column => column.key === effectiveStage);
        const next = data.columns[index + (distance < 0 ? 1 : -1)];
        if (next) setStage(next.key);
      }}>{columns.map(column => <KanbanColumn key={`${column.key}-${search}`} column={column} changedIds={changedIds} />)}</div>
    </>}
  </div>;
}

function KanbanColumn({ column, changedIds }: { column: PipelineColumn; changedIds: Set<string> }) {
  const [visibleCount, setVisibleCount] = useState(20);
  return <section className={styles.column} data-stage={column.key} aria-label={`${column.label} applications`}>
    <header><h3><i />{column.label}</h3><span>{column.items.length}</span></header>
    <div className={styles.columnBody}>{!column.items.length ? <div className={styles.empty}><span aria-hidden="true">◇</span><p>No opportunities in this stage yet.</p></div> : column.items.slice(0,visibleCount).map(item => <article key={item.id} className={styles.opportunity} data-updated={changedIds.has(item.id)}>
      <div className={styles.company}><span className={styles.avatar}>{(item.companyName || '?').slice(0,2).toUpperCase()}</span><strong>{item.companyName || 'Unknown company'}</strong></div>
      <h4>{item.roleTitle || 'Untitled role'}</h4>
      {item.followUpOverdue && <p className={styles.overdue}>Follow-up overdue</p>}<footer><span>{item.daysInStage !== null ? `${timeAgo(item.daysInStage)} in stage` : item.daysSinceActivity != null ? `${timeAgo(item.daysSinceActivity)} since activity` : 'Stage age unknown'}</span>{item.url && <a href={item.url} target="_blank" rel="noreferrer" aria-label={`Open ${item.roleTitle} at ${item.companyName}`}>↗</a>}</footer>
    </article>)}{column.items.length > visibleCount && <button onClick={() => setVisibleCount(n => n + 20)}>Show 20 more</button>}</div>
  </section>;
}
