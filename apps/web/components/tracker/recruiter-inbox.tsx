"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSessionState } from "@/hooks/use-session-state";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import styles from "./tracker-workspace.module.css";
import { listClassifiedRecruiterThreads, type ClassifiedThread, type EmailCategory } from "@/lib/tracker-api";

const CATEGORY_ORDER: EmailCategory[] = [
  "offer",
  "interview",
  "assessment",
  "verification",
  "reminder",
  "rejection",
  "applied",
  "uncategorized",
];

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return value;
  }
}

function dateGroup(value: string) {
  const date = new Date(value), today = new Date(); today.setHours(0,0,0,0);
  const week = new Date(today); week.setDate(week.getDate() - (week.getDay()+6)%7);
  if (!Number.isFinite(date.getTime())) return "Date unavailable";
  if (date >= today) return "Today";
  return date >= week ? "This week" : "Earlier";
}

export function RecruiterInbox() {
  const knownIds = useRef<Set<string> | null>(null);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<ClassifiedThread | null>(null);
  const [threads, setThreads] = useState<ClassifiedThread[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useSessionState<EmailCategory | "all">("inbox-category", "all");
  const [query, setQuery] = useSessionState("inbox-query", "");
  const [page, setPage] = useState(0);

  // An inbox with a thousand threads should not be a thousand-row page. Show a
  // fixed window and let search + paging reach the rest.
  const PAGE_SIZE = 12;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError(null);
      const result = await listClassifiedRecruiterThreads(100);
      setNewIds(new Set(result.threads.filter(thread => knownIds.current && !knownIds.current.has(thread.uid)).map(thread => thread.uid)));
      knownIds.current = new Set(result.threads.map(thread => thread.uid));
      setThreads([...result.threads].sort((a,b) => (Date.parse(b.date) || 0) - (Date.parse(a.date) || 0)));
      setCounts(result.categoryCounts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the inbox.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return threads
      .filter((t) => activeFilter === "all" || t.category === activeFilter)
      .filter(
        (t) =>
          !q ||
          [t.subject, t.fromName, t.fromAddress, t.snippet].some((v) =>
            String(v || "").toLowerCase().includes(q),
          ),
      );
  }, [threads, activeFilter, query]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visible = useMemo(
    () => filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE),
    [filtered, safePage],
  );

  // Changing filter or search should land you on the first page of the new set,
  // not on page 7 of results that no longer exist.
  useEffect(() => {
    setPage(0);
  }, [activeFilter, query]);

  return <div className={styles.workspace}>
    <div className={styles.toolbar}><div><h1>Inbox</h1></div><button onClick={() => void load()} disabled={loading}>Refresh inbox ↻</button></div>
    <div className={styles.stats}>
      {[['Recent messages', threads.length], ['Interviews', counts.interview || 0], ['Assessments', counts.assessment || 0], ['Offers', counts.offer || 0]].map(([label,value]) => <div key={label} className={styles.stat}><span>{label}</span><strong>{loading ? '—' : value}</strong></div>)}
    </div>
    {error && <div role="alert" className={styles.error}>{error}<button onClick={() => void load()}>Try again</button></div>}
    <div className={styles.inbox}>
      <aside className={styles.folders}><span className={styles.eyebrow}>YOUR INBOX</span>{(['all', ...CATEGORY_ORDER] as const).map(category => <button key={category} aria-pressed={activeFilter === category} onClick={() => {setActiveFilter(category); setSelected(null);}}><span>{category === 'all' ? 'All messages' : category}</span><b>{category === 'all' ? threads.length : counts[category] || 0}</b></button>)}</aside>
      <section className={styles.messages} aria-label="Recruiter messages">
        <label className={styles.search}>Search messages<input type="search" value={query} onChange={event => {setQuery(event.target.value); setSelected(null);}} placeholder="Sender, subject, or message…" /></label>
        <p className={styles.caption}>Up to 100 recent messages · {filtered.length} in this view · ↑ ↓ to browse</p>
        {loading ? <WorkspaceLoading label="Loading recruiter messages…" shape="list" rows={6} /> : !visible.length ? <div className={styles.empty}><span aria-hidden="true">✉</span><h3>{error ? 'Inbox unavailable' : 'Room for your next opportunity'}</h3><p>{error ? 'Retry when your email connection is available.' : threads.length ? 'No messages match these filters.' : 'Connect your email in Settings to see recruiter conversations here.'}</p></div> : visible.map((thread,index) => <Fragment key={thread.uid}>{(index === 0 || dateGroup(visible[index-1].date) !== dateGroup(thread.date)) && <h3 className={styles.dateGroup}>{dateGroup(thread.date)}</h3>}<button onKeyDown={event => {
          const index = visible.findIndex(item => item.uid === thread.uid);
          const nextIndex = event.key === "ArrowDown" ? Math.min(index + 1, visible.length - 1) : event.key === "ArrowUp" ? Math.max(index - 1, 0) : event.key === "Home" ? 0 : event.key === "End" ? visible.length - 1 : null;
          if (nextIndex === null) return;
          event.preventDefault(); setSelected(visible[nextIndex]);
          const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button[data-message]");
          buttons?.[nextIndex]?.focus();
        }} data-message="true" data-updated={newIds.has(thread.uid)} className={styles.message} aria-pressed={selected?.uid === thread.uid} onClick={() => setSelected(thread)}>
          <span className={styles.avatar}>{(thread.fromName || thread.fromAddress || '?').slice(0,1).toUpperCase()}</span><span className={styles.messageCopy}><span className={styles.sender}>{thread.fromName || thread.fromAddress}<small>{formatDate(thread.date)}</small></span><strong>{thread.subject || 'No subject'}{newIds.has(thread.uid) && <small className={styles.newMessage}>New this refresh</small>}</strong><span className={styles.snippet}>{thread.snippet || 'No preview available'}</span><span className={styles.category} data-category={thread.category}>{thread.categoryLabel || thread.category}</span></span>
        </button></Fragment>)}
        {pageCount > 1 && <div className={styles.pagination}><button disabled={safePage === 0} onClick={() => setPage(p => p - 1)}>Previous</button><span>{safePage + 1} / {pageCount}</span><button disabled={safePage >= pageCount - 1} onClick={() => setPage(p => p + 1)}>Next</button></div>}
      </section>
      <aside className={styles.preview} aria-label="Message preview">{selected ? <><span className={styles.category} data-category={selected.category}>{selected.categoryLabel || selected.category}</span><h3>{selected.subject || 'No subject'}</h3><p className={styles.caption}>{selected.fromName}<br />{selected.fromAddress} · {formatDate(selected.date)}</p><div className={styles.previewBody}>{selected.snippet || 'This message has no saved preview.'}</div><p className={styles.caption}>Saved email preview. Open your email provider to read the full message or reply.</p></> : <div className={styles.empty}><span aria-hidden="true">✉</span><p>Select a conversation to read its saved preview.</p></div>}</aside>
    </div>
  </div>;
}
