"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

type LaneFilters = {
  includeKeywords: string;
  excludeKeywords: string;
  location: string;
  company: string;
  freshness: string;
};

type Lane = {
  id: string;
  name: string;
  filters: LaneFilters;
  matchBar: number;
  dailyCap: number;
  reviewBeforeSubmit: boolean;
  enabled: boolean;
  createdAt?: string;
  lastRunAt?: string | null;
  lastRunSummary?: { staged: number } | null;
};

type LaneRunSummary = {
  laneId: string;
  name: string;
  staged: number;
  jobs: Array<{ id: string; title?: string; companyName?: string; score?: number }>;
};

type RunResult = {
  success: boolean;
  dryRun: boolean;
  queued: number;
  stagedNeedingReview?: number;
  stagedForAutosubmit?: number;
  budgetRemainingBefore?: number;
  perLane?: LaneRunSummary[];
  message?: string;
  at?: string;
};

type Status = {
  dailyCap: number;
  usedToday: number;
  remainingToday: number;
  activeLaneCount: number;
  lanes: Lane[];
};

const EMPTY_FILTERS: LaneFilters = { includeKeywords: "", excludeKeywords: "", location: "", company: "", freshness: "all" };

const FRESHNESS_OPTIONS = [
  { value: "all", label: "Any time" },
  { value: "24", label: "Last 24h" },
  { value: "48", label: "Last 48h" },
  { value: "72", label: "Last 3 days" },
  { value: "168", label: "Last week" },
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getClientApiBaseUrl()}${path}`, {
    cache: "no-store",
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload?.detail || payload?.message || `Request failed (${res.status})`);
  return payload as T;
}

function filterChips(filters: LaneFilters): string[] {
  const chips: string[] = [];
  if (filters.includeKeywords) chips.push(`includes: ${filters.includeKeywords}`);
  if (filters.excludeKeywords) chips.push(`excludes: ${filters.excludeKeywords}`);
  if (filters.location) chips.push(`loc: ${filters.location}`);
  if (filters.company) chips.push(`company: ${filters.company}`);
  if (filters.freshness && filters.freshness !== "all") {
    chips.push(FRESHNESS_OPTIONS.find((f) => f.value === filters.freshness)?.label ?? filters.freshness);
  }
  return chips.length ? chips : ["No filters — every discovered role is a candidate"];
}

function LaneEditor({
  initial,
  onCancel,
  onSave,
  saving,
}: {
  initial: Partial<Lane> | null;
  onCancel: () => void;
  onSave: (draft: Pick<Lane, "name" | "filters" | "matchBar" | "dailyCap" | "reviewBeforeSubmit" | "enabled">) => void;
  saving: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [filters, setFilters] = useState<LaneFilters>({ ...EMPTY_FILTERS, ...(initial?.filters ?? {}) });
  const [matchBar, setMatchBar] = useState(initial?.matchBar ?? 60);
  const [dailyCap, setDailyCap] = useState(initial?.dailyCap ?? 5);
  const [reviewBeforeSubmit, setReviewBeforeSubmit] = useState(initial?.reviewBeforeSubmit ?? true);
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);

  return (
    <div className="workflow-panel" style={{ border: "1px solid rgba(46,232,201,0.35)", background: "#0c1820" }}>
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">{initial?.id ? "Edit lane" : "New lane"}</span>
          <h3 className="text-sm font-semibold text-white">Saved-search config</h3>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-3">
        <label className="flex flex-col gap-1 text-xs text-slate-300 sm:col-span-2">
          Lane name
          <input
            className="input"
            value={name}
            placeholder="e.g. Senior backend, remote"
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-300">
          Include keywords (title or description, comma-separated)
          <input
            className="input"
            value={filters.includeKeywords}
            placeholder="e.g. backend, platform"
            onChange={(e) => setFilters({ ...filters, includeKeywords: e.target.value })}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-300">
          Exclude keywords
          <input
            className="input"
            value={filters.excludeKeywords}
            placeholder="e.g. staffing, contract"
            onChange={(e) => setFilters({ ...filters, excludeKeywords: e.target.value })}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-300">
          Location contains
          <input
            className="input"
            value={filters.location}
            placeholder="e.g. remote, NYC"
            onChange={(e) => setFilters({ ...filters, location: e.target.value })}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-300">
          Company contains
          <input
            className="input"
            value={filters.company}
            onChange={(e) => setFilters({ ...filters, company: e.target.value })}
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-300">
          Posted within
          <select className="input" value={filters.freshness} onChange={(e) => setFilters({ ...filters, freshness: e.target.value })}>
            {FRESHNESS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-300">
          Match bar — minimum score to qualify
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={0}
              max={100}
              value={matchBar}
              onChange={(e) => setMatchBar(Number(e.target.value))}
              className="w-full accent-[#2ee8c9]"
            />
            <span className="text-[#2ee8c9] font-mono text-xs w-10 text-right">{matchBar}%</span>
          </div>
        </label>

        <label className="flex flex-col gap-1 text-xs text-slate-300">
          Lane daily cap
          <input
            type="number"
            min={1}
            max={100}
            className="input"
            value={dailyCap}
            onChange={(e) => setDailyCap(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>

        <label className="flex items-center gap-2 text-xs text-slate-300 sm:col-span-2">
          <input type="checkbox" checked={reviewBeforeSubmit} onChange={(e) => setReviewBeforeSubmit(e.target.checked)} />
          Review before submit — stage matches for Review Center instead of auto-submitting
        </label>

        <label className="flex items-center gap-2 text-xs text-slate-300 sm:col-span-2">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Lane active
        </label>
      </div>

      <div className="flex items-center gap-2 mt-4">
        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={!name.trim() || saving}
          onClick={() => onSave({ name: name.trim(), filters, matchBar, dailyCap, reviewBeforeSubmit, enabled })}
        >
          {saving ? "Saving…" : "Save lane"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

export function AutoApplyPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [log, setLog] = useState<RunResult[]>([]);
  const [error, setError] = useState("");
  const [lastRun, setLastRun] = useState<RunResult | null>(null);
  const [editingId, setEditingId] = useState<string | "new" | null>(null);
  const [savingLane, setSavingLane] = useState(false);
  const [running, setRunning] = useState(false);
  const [capDraft, setCapDraft] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [statusRes, logRes] = await Promise.all([
        api<{ success: boolean } & Status>("/intelligence/auto-apply/status"),
        api<{ success: boolean; log: RunResult[] }>("/intelligence/auto-apply/lanes/log"),
      ]);
      setStatus(statusRes);
      setLog(logRes.log || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Auto Apply lanes");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSaveLane(draft: Pick<Lane, "name" | "filters" | "matchBar" | "dailyCap" | "reviewBeforeSubmit" | "enabled">) {
    setSavingLane(true);
    try {
      if (editingId && editingId !== "new") {
        await api(`/intelligence/auto-apply/lanes/${editingId}`, { method: "PATCH", body: JSON.stringify(draft) });
      } else {
        await api("/intelligence/auto-apply/lanes", { method: "POST", body: JSON.stringify(draft) });
      }
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save lane");
    } finally {
      setSavingLane(false);
    }
  }

  async function handleToggle(lane: Lane, patch: Partial<Lane>) {
    setStatus((prev) => prev ? { ...prev, lanes: prev.lanes.map((l) => (l.id === lane.id ? { ...l, ...patch } : l)) } : prev);
    try {
      await api(`/intelligence/auto-apply/lanes/${lane.id}`, { method: "PATCH", body: JSON.stringify(patch) });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update lane");
      await load();
    }
  }

  async function handleDelete(laneId: string) {
    try {
      await api(`/intelligence/auto-apply/lanes/${laneId}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete lane");
    }
  }

  async function handleRun(dryRun: boolean) {
    setRunning(true);
    setError("");
    try {
      const result = await api<RunResult>(`/intelligence/auto-apply/lanes/run?dry_run=${dryRun}`, { method: "POST" });
      setLastRun(result);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Run failed");
    } finally {
      setRunning(false);
    }
  }

  async function handleSaveCap() {
    if (capDraft == null) return;
    try {
      await api("/intelligence/auto-apply/cap", { method: "PUT", body: JSON.stringify({ dailyCap: capDraft }) });
      setCapDraft(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update shared cap");
    }
  }

  if (!status) {
    return error ? <p className="muted">{error}</p> : <p className="muted">Loading Auto Apply lanes…</p>;
  }

  const capPct = status.dailyCap > 0 ? Math.min(100, Math.round((status.usedToday / status.dailyCap) * 100)) : 0;

  return (
    <div className="intelligence-panel space-y-4">
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Shared daily cap</span>
            <h2 className="text-sm font-semibold text-white">
              {status.usedToday} / {status.dailyCap} applications submitted today
            </h2>
            <p className="muted">Every lane draws from this one budget, best matches first. Adding a lane changes what gets considered, not how much gets applied to.</p>
          </div>
          <div className="target-jobs-actions flex items-center gap-2">
            <button type="button" className="btn btn-sm" onClick={() => void handleRun(true)} disabled={running}>
              {running ? "Running…" : "Preview run"}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => void handleRun(false)}
              disabled={running || status.activeLaneCount === 0}
            >
              Run now
            </button>
          </div>
        </div>
        <div className="w-full h-2 rounded-full bg-[#0c1820] border border-[#2ee8c9]/30 overflow-hidden mt-2">
          <div
            className="h-full rounded-full bg-[#2ee8c9] shadow-[0_0_10px_rgba(46,232,201,0.7)] transition-all"
            style={{ width: `${capPct}%` }}
          />
        </div>
        <div className="flex items-center gap-2 mt-3 text-xs text-slate-300">
          <span>Change daily cap:</span>
          <input
            type="number"
            min={1}
            max={200}
            className="input w-20"
            value={capDraft ?? status.dailyCap}
            onChange={(e) => setCapDraft(Number(e.target.value) || 1)}
          />
          {capDraft != null && capDraft !== status.dailyCap ? (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void handleSaveCap()}>Save</button>
          ) : null}
        </div>
        {error ? <p className="text-rose-400 text-xs mt-2">{error}</p> : null}
      </section>

      {lastRun ? (
        <section className="workflow-panel data-panel">
          <span className="toc-card-kicker">{lastRun.dryRun ? "Preview result" : "Run result"}</span>
          <p className="muted">
            {lastRun.message || `Queued ${lastRun.queued} — ${lastRun.stagedNeedingReview ?? 0} staged for review, ${lastRun.stagedForAutosubmit ?? 0} handed to Autopilot.`}
          </p>
          {lastRun.perLane?.filter((l) => l.staged > 0).map((lane) => (
            <div key={lane.laneId} className="data-row">
              <span>{lane.name}</span>
              <small className="muted">{lane.staged} staged</small>
            </div>
          ))}
        </section>
      ) : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Lanes ({status.lanes.length}/5 · {status.activeLaneCount} active)</h3>
          {editingId !== "new" ? (
            <button
              type="button"
              className="btn btn-sm"
              disabled={status.lanes.length >= 5}
              onClick={() => setEditingId("new")}
            >
              + Add a lane
            </button>
          ) : null}
        </div>

        {editingId === "new" ? (
          <LaneEditor initial={null} onCancel={() => setEditingId(null)} onSave={handleSaveLane} saving={savingLane} />
        ) : null}

        {status.lanes.length === 0 && editingId !== "new" ? (
          <p className="muted">No lanes yet — add one to start scoring and staging matches automatically.</p>
        ) : null}

        {status.lanes.map((lane) =>
          editingId === lane.id ? (
            <LaneEditor key={lane.id} initial={lane} onCancel={() => setEditingId(null)} onSave={handleSaveLane} saving={savingLane} />
          ) : (
            <div key={lane.id} className="workflow-panel">
              <div className="dashboard-panel-header">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-white">{lane.name}</h3>
                    <span
                      className="px-1.5 py-0.5 rounded-full text-[10px] font-black border"
                      style={
                        lane.enabled
                          ? { color: "#2ee8c9", borderColor: "rgba(46,232,201,0.4)", background: "rgba(46,232,201,0.08)" }
                          : { color: "#94a3b8", borderColor: "rgba(148,163,184,0.3)", background: "rgba(148,163,184,0.06)" }
                      }
                    >
                      {lane.enabled ? "ACTIVE" : "PAUSED"}
                    </span>
                    {lane.reviewBeforeSubmit ? (
                      <span className="px-1.5 py-0.5 rounded-full text-[10px] font-black border" style={{ color: "#c084fc", borderColor: "rgba(168,85,247,0.4)", background: "rgba(168,85,247,0.08)" }}>
                        REVIEW FIRST
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.5 rounded-full text-[10px] font-black border" style={{ color: "#34d399", borderColor: "rgba(52,211,153,0.4)", background: "rgba(52,211,153,0.08)" }}>
                        AUTO-SUBMIT
                      </span>
                    )}
                  </div>
                  <p className="muted mt-1">{filterChips(lane.filters).join(" · ")}</p>
                  <p className="muted mt-1">
                    Match bar ≥{lane.matchBar}% · cap {lane.dailyCap}/day
                    {lane.lastRunAt ? ` · last run staged ${lane.lastRunSummary?.staged ?? 0}` : " · never run"}
                  </p>
                </div>
                <div className="target-jobs-actions flex items-center gap-2">
                  <label className="flex items-center gap-1 text-xs text-slate-300">
                    <input type="checkbox" checked={lane.enabled} onChange={(e) => void handleToggle(lane, { enabled: e.target.checked })} />
                    On
                  </label>
                  <button type="button" className="btn btn-sm" onClick={() => setEditingId(lane.id)}>Edit</button>
                  <button type="button" className="btn btn-sm" onClick={() => void handleDelete(lane.id)}>Delete</button>
                </div>
              </div>
            </div>
          ),
        )}
      </section>

      <section className="workflow-panel data-panel">
        <span className="toc-card-kicker">Run log</span>
        {!log.length ? <p className="muted">No runs yet.</p> : (
          <div className="data-list">
            {log.map((entry, index) => (
              <div className="data-row" key={index}>
                <span>{entry.message || `Queued ${entry.queued} (${entry.dryRun ? "preview" : "live"})`}</span>
                <small className="muted">{entry.at}</small>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
