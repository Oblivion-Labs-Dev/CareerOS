"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

type AutoApplySettings = { enabled: boolean; max_per_run: number; enabled_roles: string; dry_run_default: boolean };

export function AutoApplyPanel() {
  const [settings, setSettings] = useState<AutoApplySettings | null>(null);
  const [log, setLog] = useState<Array<{ action?: string; message?: string; at?: string }>>([]);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    const base = getClientApiBaseUrl();
    const [settingsRes, logRes] = await Promise.all([
      fetch(`${base}/intelligence/auto-apply/settings`, { cache: "no-store" }),
      fetch(`${base}/intelligence/auto-apply/log`, { cache: "no-store" }),
    ]);
    if (settingsRes.ok) {
      const payload = (await settingsRes.json()) as { settings: AutoApplySettings };
      setSettings(payload.settings);
    }
    if (logRes.ok) {
      const payload = (await logRes.json()) as { log: typeof log };
      setLog(payload.log || []);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(patch: Partial<AutoApplySettings>) {
    if (!settings) return;
    setSettings({ ...settings, ...patch });
    await fetch(`${getClientApiBaseUrl()}/intelligence/auto-apply/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  }

  async function run(dryRun: boolean) {
    const res = await fetch(`${getClientApiBaseUrl()}/intelligence/auto-apply/run?dry_run=${dryRun}`, { method: "POST" });
    const payload = await res.json();
    setMsg(payload.message || "Run complete");
    void load();
  }

  if (!settings) return <p className="muted">Loading auto apply…</p>;

  return (
    <div className="intelligence-panel">
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Auto Apply</span>
            <h2>Programmatic ATS submission</h2>
            <p className="muted">Use with ApplyPilot extension for form fill. Tier-1 companies always excluded.</p>
          </div>
          <div className="target-jobs-actions">
            <button type="button" className="btn btn-sm" onClick={() => void run(true)}>Dry run</button>
            <button type="button" className="btn btn-sm btn-primary" onClick={() => void run(false)} disabled={!settings.enabled}>Run</button>
          </div>
        </div>
        <label className="intelligence-toggle">
          <input type="checkbox" checked={settings.enabled} onChange={(e) => void save({ enabled: e.target.checked })} />
          <span>Auto Apply enabled</span>
        </label>
        {msg ? <p className="muted">{msg}</p> : null}
      </section>
      <section className="workflow-panel data-panel">
        <span className="toc-card-kicker">Log</span>
        {!log.length ? <p className="muted">No runs yet.</p> : (
          <div className="data-list">
            {log.map((entry, index) => (
              <div className="data-row" key={index}>
                <span>{entry.message}</span>
                <small className="muted">{entry.at}</small>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
