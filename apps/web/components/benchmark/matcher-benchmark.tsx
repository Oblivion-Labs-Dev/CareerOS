"use client";

import { useEffect, useState } from "react";

type ApproachRow = {
  approach: string;
  rocAuc: number | null;
  prAuc: number | null;
  pairwise: number | null;
  latencyMs: number | null;
  rescore851Seconds: number | null;
  modelMb?: number;
  stable?: boolean;
  adversarialPassed?: number;
  gate?: { precision: number | null; recall: number | null; falseAutoApplies: number } | null;
};

type Payload = {
  available: boolean;
  reason?: string;
  verdict?: {
    bestQuality: string;
    bestQualityAuc: number;
    fastest: string;
    fastestMs: number;
    rescore851Seconds: number;
  };
  leaderboard?: { generatedAt?: string; evaluation?: Record<string, unknown>; results: ApproachRow[] };
  ablation?: { subsets: Array<{ signals: string[]; rocAuc: number | null; gateRecall: number | null; adversarialPassed: number }> };
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:4000";

/** Approaches CareerOS currently uses, so the page shows where we stand today. */
const CURRENT = "naive-coverage";

function fmt(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export function MatcherBenchmark() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/matcher-benchmark`, { credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`API returned ${res.status}`);
        return res.json();
      })
      .then((payload) => !cancelled && setData(payload))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <article className="workflow-panel">
        <h2>Matcher benchmark</h2>
        <p className="muted">Could not load results: {error}</p>
      </article>
    );
  }
  if (!data) {
    return (
      <article className="workflow-panel">
        <h2>Matcher benchmark</h2>
        <p className="muted">Loading…</p>
      </article>
    );
  }
  if (!data.available) {
    return (
      <article className="workflow-panel">
        <h2>Matcher benchmark</h2>
        <p className="muted">{data.reason}</p>
      </article>
    );
  }

  const results = [...(data.leaderboard?.results ?? [])].sort(
    (a, b) => (b.rocAuc ?? -1) - (a.rocAuc ?? -1),
  );
  const current = results.find((r) => r.approach === CURRENT);
  const best = results[0];

  return (
    <>
      <article className="workflow-panel dashboard-panel--wide">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Matcher benchmark</span>
            <h2>Which scorer should decide whether to apply?</h2>
            <p className="muted" style={{ marginTop: "0.4rem", maxWidth: "62ch" }}>
              Nine approaches over {String((data.leaderboard?.evaluation as never)?.["jobs"] ?? "—")} real
              postings, CPU only, one model resident at a time. Ranked by ROC-AUC — the
              probability a suitable posting outranks an unsuitable one.
            </p>
          </div>
        </div>

        <div className="matcher-verdicts">
          <div className="matcher-verdict">
            <span className="matcher-verdict-label">Best quality</span>
            <strong>{data.verdict?.bestQuality}</strong>
            <span className="muted">{fmt(data.verdict?.bestQualityAuc)} ROC-AUC</span>
          </div>
          <div className="matcher-verdict">
            <span className="matcher-verdict-label">Rescore 851 jobs</span>
            <strong>{duration(data.verdict?.rescore851Seconds)}</strong>
            <span className="muted">vs ~21h for the 7B model</span>
          </div>
          {current ? (
            <div className="matcher-verdict matcher-verdict--warn">
              <span className="matcher-verdict-label">Currently shipping</span>
              <strong>{fmt(current.rocAuc)}</strong>
              <span className="muted">
                {(current.rocAuc ?? 0) < 0.5
                  ? "below chance — ranks bad jobs above good ones"
                  : "in production today"}
              </span>
            </div>
          ) : null}
        </div>

        <div className="matcher-tablewrap">
          <table className="matcher-table">
            <thead>
              <tr>
                <th>Approach</th>
                <th>ROC-AUC</th>
                <th>PR-AUC</th>
                <th>Auto-apply precision</th>
                <th>Recall</th>
                <th>Latency</th>
                <th>851 jobs</th>
                <th>Model</th>
                <th>Adversarial</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => {
                const isBest = row.approach === best?.approach;
                const isCurrent = row.approach === CURRENT;
                return (
                  <tr
                    key={row.approach}
                    className={isBest ? "is-best" : isCurrent ? "is-current" : undefined}
                  >
                    <td className="mono">
                      {row.approach}
                      {isCurrent ? <span className="matcher-tag">current</span> : null}
                    </td>
                    <td className="num">{fmt(row.rocAuc)}</td>
                    <td className="num">{fmt(row.prAuc)}</td>
                    <td className="num">{fmt(row.gate?.precision ?? null)}</td>
                    <td className="num">{fmt(row.gate?.recall ?? null)}</td>
                    <td className="num">{row.latencyMs ? `${row.latencyMs}ms` : "—"}</td>
                    <td className="num">{duration(row.rescore851Seconds)}</td>
                    <td className="num">{row.modelMb ? `${row.modelMb}MB` : "0"}</td>
                    <td className="num">
                      {row.adversarialPassed === undefined ? "—" : `${row.adversarialPassed}/3`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: "0.85rem", marginTop: "0.75rem" }}>
          Auto-apply precision is the deciding metric: a good job sent to review costs a
          click, an automatic application to the wrong job cannot be undone. Recall is the
          share of good jobs the gate would auto-apply to at full precision.
        </p>
      </article>

      {data.ablation?.subsets?.length ? (
        <article className="workflow-panel dashboard-panel--wide">
          <div className="dashboard-panel-header">
            <div>
              <span className="toc-card-kicker">Ablation</span>
              <h2>What actually carries the signal</h2>
              <p className="muted" style={{ marginTop: "0.4rem", maxWidth: "62ch" }}>
                Every subset of the winning scorer&apos;s signals. Role family alone reaches
                0.912; remove it and everything else together reaches 0.778.
              </p>
            </div>
          </div>
          <div className="matcher-tablewrap">
            <table className="matcher-table">
              <thead>
                <tr>
                  <th>Signals</th>
                  <th>ROC-AUC</th>
                  <th>Gate recall</th>
                  <th>Adversarial</th>
                </tr>
              </thead>
              <tbody>
                {data.ablation.subsets.slice(0, 10).map((row) => (
                  <tr key={row.signals.join("+")}>
                    <td className="mono">{row.signals.join(" + ")}</td>
                    <td className="num">{fmt(row.rocAuc)}</td>
                    <td className="num">{fmt(row.gateRecall)}</td>
                    <td className="num">{row.adversarialPassed}/3</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ) : null}
    </>
  );
}
