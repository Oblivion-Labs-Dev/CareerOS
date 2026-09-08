"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  downloadApplicationsCsv,
  getTrackerPipeline,
  importApplicationsCsv,
  type PipelineColumn,
  type PipelineColumnKey,
  type PipelineResponse,
} from "@/lib/tracker-api";

const COLUMN_STYLE: Record<PipelineColumnKey, { text: string; border: string; bgActive: string; glow: string }> = {
  applied: { text: "#fbbf24", border: "rgba(245, 158, 11, 0.4)", bgActive: "#2c1d0c", glow: "rgba(245, 158, 11, 0.28)" },
  ghosted: { text: "#94a3b8", border: "rgba(148, 163, 184, 0.35)", bgActive: "#1a1f28", glow: "rgba(148, 163, 184, 0.18)" },
  interviewing: { text: "#a5b4fc", border: "rgba(129, 140, 248, 0.4)", bgActive: "#181d3c", glow: "rgba(129, 140, 248, 0.28)" },
  rejected: { text: "#fb7185", border: "rgba(244, 63, 94, 0.4)", bgActive: "#2a0d14", glow: "rgba(244, 63, 94, 0.24)" },
  offer: { text: "#34d399", border: "rgba(52, 211, 153, 0.4)", bgActive: "#0a241b", glow: "rgba(52, 211, 153, 0.3)" },
};

function timeAgo(days: number | null): string {
  if (days === null) return "—";
  if (days <= 0) return "today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

export function PipelineKanban() {
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

  if (loading) {
    return <p className="text-sm text-slate-400 px-1">Loading pipeline…</p>;
  }

  if (error) {
    return (
      <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
        {error}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-5">
      {/* Funnel strip */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.02] px-5 py-4">
        <div className="flex flex-wrap items-center gap-6">
          {data.funnel.map((stage, i) => {
            const style = COLUMN_STYLE[stage.key];
            return (
              <div key={stage.key} className="flex items-center gap-6">
                <div className="flex flex-col">
                  <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: style.text }}>
                    {stage.label}
                  </span>
                  <span className="text-xl font-black text-white tabular-nums">{stage.count}</span>
                </div>
                {i < data.funnel.length - 1 && <span className="text-slate-600">→</span>}
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-2.5">
          <input ref={fileInputRef} type="file" accept=".csv,text/csv" className="hidden" onChange={handleFileChange} />
          <button
            type="button"
            onClick={handleImportClick}
            disabled={importBusy}
            className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-bold text-slate-200 transition hover:bg-white/10 disabled:opacity-50"
          >
            {importBusy ? "Importing…" : "Import CSV"}
          </button>
          <button
            type="button"
            onClick={() => downloadApplicationsCsv()}
            className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-bold text-slate-200 transition hover:bg-white/10"
          >
            Export CSV
          </button>
        </div>
      </div>

      {importMessage && (
        <p className="px-1 text-xs text-slate-400">{importMessage}</p>
      )}

      {/* Kanban columns */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {data.columns.map((column) => (
          <KanbanColumn key={column.key} column={column} />
        ))}
      </div>
    </div>
  );
}

function KanbanColumn({ column }: { column: PipelineColumn }) {
  const style = COLUMN_STYLE[column.key];
  return (
    <div
      className="flex min-h-[220px] max-h-[32rem] flex-col gap-3 overflow-hidden rounded-xl border p-3.5"
      style={{ borderColor: style.border, background: "rgba(255,255,255,0.02)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-black uppercase tracking-widest" style={{ color: style.text }}>
          {column.label}
        </span>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-black"
          style={{ background: style.glow, color: style.text }}
        >
          {column.items.length}
        </span>
      </div>

      {column.items.length === 0 ? (
        <p className="text-xs text-slate-500">Nothing here.</p>
      ) : (
        // Scrolls within the column rather than growing it: with a thousand
        // applications in one stage the board itself must stay a fixed height.
        <div className="flex flex-col gap-2 overflow-y-auto overscroll-contain pr-1">
          {column.items.map((item) => (
            <a
              key={item.id}
              href={item.url || undefined}
              target={item.url ? "_blank" : undefined}
              rel={item.url ? "noreferrer" : undefined}
              className="block rounded-lg border border-white/10 bg-[#0c1017]/80 px-3 py-2.5 transition hover:border-white/25 hover:bg-[#0c1017]"
            >
              <p className="truncate text-xs font-bold text-white">{item.companyName}</p>
              <p className="truncate text-[11px] text-slate-400">{item.roleTitle}</p>
              <p className="mt-1 text-[10px] font-semibold uppercase tracking-wide" style={{ color: style.text }}>
                {timeAgo(item.daysInStage)} in stage
              </p>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
