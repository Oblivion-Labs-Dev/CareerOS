"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

type NightShiftSettings = {
  enabled: boolean;
  max_per_night: number;
  min_fit_score: number;
  enabled_roles: string;
};

type QueueItem = {
  id: string;
  companyName: string;
  title: string;
  relevancyScore?: number;
  status: string;
  url?: string;
};

export function NightShiftPanel() {
  const [settings, setSettings] = useState<NightShiftSettings | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [tiers, setTiers] = useState<{ tier_1_never_apply: string[]; tier_2_eligible: string[] } | null>(null);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const base = getClientApiBaseUrl();
    const [settingsRes, queueRes, tiersRes] = await Promise.all([
      fetch(`${base}/intelligence/night-shift/settings`, { cache: "no-store" }),
      fetch(`${base}/intelligence/night-shift/queue`, { cache: "no-store" }),
      fetch(`${base}/intelligence/night-shift/tiers`, { cache: "no-store" }),
    ]);
    if (settingsRes.ok) {
      const payload = (await settingsRes.json()) as { settings: NightShiftSettings };
      setSettings(payload.settings);
    }
    if (queueRes.ok) {
      const payload = (await queueRes.json()) as { queue: QueueItem[] };
      setQueue(payload.queue || []);
    }
    if (tiersRes.ok) {
      setTiers(await tiersRes.json());
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function saveSettings(patch: Partial<NightShiftSettings>) {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    await fetch(`${getClientApiBaseUrl()}/intelligence/night-shift/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  }

  async function runSelect(dryRun: boolean) {
    setMsg("Selecting…");
    const res = await fetch(`${getClientApiBaseUrl()}/intelligence/night-shift/select?dry_run=${dryRun}`, { method: "POST" });
    const payload = await res.json();
    setMsg(payload.message || `Queued ${payload.queued ?? 0} roles`);
    void load();
  }

  if (loading || !settings) return <p className="muted">Loading Night Shift…</p>;

  return (
    <div className="intelligence-panel">
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Night Shift</span>
            <h2>Tier-2 auto-fill queue</h2>
            <p className="muted">Never touches Tier-1 dream companies. Fills forms overnight for morning review.</p>
          </div>
          <div className="target-jobs-actions">
            <button type="button" className="btn btn-sm" onClick={() => void runSelect(true)}>Preview</button>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void runSelect(false)} disabled={!settings.enabled}>
              Select tonight
            </button>
          </div>
        </div>
        <label className="intelligence-toggle">
          <input type="checkbox" checked={settings.enabled} onChange={(e) => void saveSettings({ enabled: e.target.checked })} />
          <span>Night Shift enabled</span>
        </label>
        <div className="target-jobs-filters">
          <label>Max per night<input type="number" value={settings.max_per_night} onChange={(e) => void saveSettings({ max_per_night: Number(e.target.value) })} /></label>
          <label>Min fit score<input type="number" value={settings.min_fit_score} onChange={(e) => void saveSettings({ min_fit_score: Number(e.target.value) })} /></label>
          <label>Roles<input value={settings.enabled_roles} onChange={(e) => void saveSettings({ enabled_roles: e.target.value })} placeholder="pm,tpm,product" /></label>
        </div>
        {msg ? <p className="muted">{msg}</p> : null}
      </section>
      {tiers ? (
        <section className="workflow-panel">
          <span className="toc-card-kicker">Tier guardrails</span>
          <p className="muted">{tiers.tier_1_never_apply.length} Tier-1 companies blocked · {tiers.tier_2_eligible.length} Tier-2 eligible</p>
        </section>
      ) : null}
      <section className="workflow-panel data-panel">
        <span className="toc-card-kicker">Review queue</span>
        <h2>{queue.length} items</h2>
        {!queue.length ? <p className="muted">Run a job scrape first, then preview or select Tier-2 roles.</p> : (
          <div className="data-list">
            {queue.map((item) => (
              <div className="data-row job-discover-row" key={item.id}>
                <div>
                  <h3>{item.title}</h3>
                  <span>{item.companyName} · {item.relevancyScore ?? 0}% · {item.status}</span>
                </div>
                {item.url ? <a className="btn btn-sm" href={item.url} target="_blank" rel="noreferrer">Open</a> : null}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
