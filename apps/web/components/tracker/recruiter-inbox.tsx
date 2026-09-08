"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { listClassifiedRecruiterThreads, type ClassifiedThread, type EmailCategory } from "@/lib/tracker-api";

const CATEGORY_STYLE: Record<EmailCategory, { text: string; bg: string; border: string }> = {
  offer: { text: "#2ee8c9", bg: "rgba(46, 232, 201, 0.14)", border: "rgba(46, 232, 201, 0.4)" },
  interview: { text: "#34d399", bg: "rgba(52, 211, 153, 0.14)", border: "rgba(52, 211, 153, 0.4)" },
  assessment: { text: "#c084fc", bg: "rgba(168, 85, 247, 0.14)", border: "rgba(168, 85, 247, 0.4)" },
  verification: { text: "#a5b4fc", bg: "rgba(129, 140, 248, 0.14)", border: "rgba(129, 140, 248, 0.4)" },
  reminder: { text: "#fbbf24", bg: "rgba(245, 158, 11, 0.14)", border: "rgba(245, 158, 11, 0.4)" },
  rejection: { text: "#fb7185", bg: "rgba(244, 63, 94, 0.14)", border: "rgba(244, 63, 94, 0.4)" },
  applied: { text: "#94a3b8", bg: "rgba(148, 163, 184, 0.12)", border: "rgba(148, 163, 184, 0.35)" },
  uncategorized: { text: "#64748b", bg: "rgba(100, 116, 139, 0.1)", border: "rgba(100, 116, 139, 0.3)" },
};

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

function CategoryChip({ category, label }: { category: EmailCategory; label: string }) {
  const style = CATEGORY_STYLE[category];
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wide"
      style={{ color: style.text, background: style.bg, borderColor: style.border }}
    >
      {label}
    </span>
  );
}

export function RecruiterInbox() {
  const [threads, setThreads] = useState<ClassifiedThread[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<EmailCategory | "all">("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);

  // An inbox with a thousand threads should not be a thousand-row page. Show a
  // fixed window and let search + paging reach the rest.
  const PAGE_SIZE = 12;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError(null);
      const result = await listClassifiedRecruiterThreads(500);
      setThreads(result.threads);
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

  if (loading) {
    return <p className="text-sm text-slate-400 px-1">Classifying recruiter email…</p>;
  }

  if (error) {
    return (
      <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setActiveFilter("all")}
          className="rounded-full border px-3 py-1 text-[11px] font-bold uppercase tracking-wide transition"
          style={
            activeFilter === "all"
              ? { color: "#0c1017", background: "#e2e8f0", borderColor: "#e2e8f0" }
              : { color: "#94a3b8", background: "transparent", borderColor: "rgba(148,163,184,0.3)" }
          }
        >
          All ({threads.length})
        </button>
        {CATEGORY_ORDER.filter((category) => counts[category]).map((category) => {
          const style = CATEGORY_STYLE[category];
          const active = activeFilter === category;
          return (
            <button
              key={category}
              type="button"
              onClick={() => setActiveFilter(category)}
              className="rounded-full border px-3 py-1 text-[11px] font-bold uppercase tracking-wide transition"
              style={
                active
                  ? { color: "#0c1017", background: style.text, borderColor: style.text }
                  : { color: style.text, background: style.bg, borderColor: style.border }
              }
            >
              {category} ({counts[category]})
            </button>
          );
        })}
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search sender, subject…"
          className="ml-auto min-w-[12rem] flex-1 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-slate-200 outline-none placeholder:text-slate-500 focus:border-white/25"
        />
      </div>

      {filtered.length === 0 ? (
        <p className="rounded-xl border border-white/10 bg-white/[0.02] px-4 py-6 text-center text-sm text-slate-400">
          {threads.length === 0
            ? "No recruiter email found yet. Connect Gmail in Settings to populate this inbox."
            : "No threads in this category."}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {visible.map((thread) => (
            <div
              key={thread.uid}
              className="flex flex-col gap-1.5 rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <CategoryChip category={thread.category} label={thread.categoryLabel} />
                  <p className="truncate text-sm font-bold text-white">{thread.subject}</p>
                </div>
                <p className="mt-1 truncate text-xs text-slate-400">
                  {thread.fromName || thread.fromAddress}
                  {thread.snippet ? ` — ${thread.snippet}` : ""}
                </p>
              </div>
              <span className="shrink-0 text-[11px] text-slate-500">{formatDate(thread.date)}</span>
            </div>
          ))}
        </div>
      )}

      {filtered.length > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-3 pt-1">
          <span className="text-[11px] text-slate-500">
            {safePage * PAGE_SIZE + 1}–{Math.min(filtered.length, (safePage + 1) * PAGE_SIZE)} of{" "}
            {filtered.length}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-[11px] font-bold text-slate-200 transition hover:bg-white/10 disabled:opacity-40"
            >
              Previous
            </button>
            <span className="text-[11px] text-slate-500">
              {safePage + 1} / {pageCount}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={safePage >= pageCount - 1}
              className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1 text-[11px] font-bold text-slate-200 transition hover:bg-white/10 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
