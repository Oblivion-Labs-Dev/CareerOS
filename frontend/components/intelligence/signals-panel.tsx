"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

type Signal = { id?: string; author?: string; text?: string; hiring_intent?: number; action?: string };

export function SignalsPanel() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [stats, setStats] = useState<{ total: number; highIntent: number; lastScan?: string } | null>(null);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const base = getClientApiBaseUrl();
    const [listRes, statsRes] = await Promise.all([
      fetch(`${base}/intelligence/signals`, { cache: "no-store" }),
      fetch(`${base}/intelligence/signals/stats`, { cache: "no-store" }),
    ]);
    if (listRes.ok) {
      const payload = (await listRes.json()) as { signals: Signal[] };
      setSignals(payload.signals || []);
    }
    if (statsRes.ok) setStats(await statsRes.json());
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function scan() {
    setMsg("Scanning…");
    const res = await fetch(`${getClientApiBaseUrl()}/intelligence/signals/scan`, { method: "POST" });
    const payload = await res.json();
    setMsg(payload.message || "Scan complete");
    void load();
  }

  if (loading) return <p className="muted">Loading signals…</p>;

  return (
    <div className="intelligence-panel">
      <section className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Signals</span>
            <h2>LinkedIn hiring intent</h2>
            <p className="muted">{stats?.total ?? 0} signals · {stats?.highIntent ?? 0} high intent</p>
          </div>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => void scan()}>Scan posts</button>
        </div>
        {msg ? <p className="muted">{msg}</p> : null}
      </section>
      <section className="workflow-panel data-panel">
        {!signals.length ? (
          <p className="muted">No signals yet. Configure APIFY_TOKEN to scan LinkedIn hiring posts, or add signals manually via API.</p>
        ) : (
          <div className="data-list">
            {signals.map((signal, index) => (
              <div className="data-row" key={signal.id || index}>
                <div>
                  <h3>{signal.author || "Unknown author"}</h3>
                  <span>{signal.text?.slice(0, 180)}{(signal.text?.length ?? 0) > 180 ? "…" : ""}</span>
                </div>
                <span className="discover-score">{signal.hiring_intent ?? 0}%</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
