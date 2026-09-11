"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * What the optional Gemini layer is doing, and whether CareerOS is currently
 * relying on it at all.
 *
 * The question this page has to answer at a glance is not "is Gemini fast" but
 * "is anything broken because Gemini is not available". So the health state and
 * the fallback counts lead; latency and tokens are detail below the fold.
 */

type Circuit = {
  state: "CLOSED" | "OPEN" | "HALF_OPEN";
  consecutiveFailures: number;
  cooldownSeconds: number;
  secondsUntilRetry: number;
  reason: string;
};

type TaskCounts = {
  requests: number;
  success: number;
  failure: number;
  cacheHits: number;
  fallbacks: number;
};

type Metrics = {
  requests: number;
  apiCalls: number;
  successes: number;
  failures: number;
  successRate: number | null;
  cacheHits: number;
  dedupeHits: number;
  cacheHitRate: number | null;
  retries: number;
  rateLimited429: number;
  serverErrors503: number;
  configErrors404: number;
  permanentErrors: number;
  malformedResponses: number;
  timeouts: number;
  circuitRejections: number;
  fallbacks: number;
  applicationsStagedForReview: number;
  byTask: Record<string, TaskCounts>;
  latencyMs: { average: number | null; p50: number | null; p95: number | null; samples: number };
  tokens: { prompt: number; completion: number; total: number };
  estimatedCostUsd: number;
  estimatedCostNote: string;
  recentFailures: Array<{ at: string; task: string; outcome: string; detail: string }>;
};

type Payload = {
  health: "HEALTHY" | "RATE LIMITED" | "CIRCUIT OPEN" | "DISABLED";
  enabled: boolean;
  configured: boolean;
  model: string;
  baseUrl: string;
  limits: Record<string, number>;
  circuit: Circuit;
  queue: { depth: number; byPriority: Record<string, number>; inFlight: number; workers: number; concurrency: number };
  metrics: Metrics;
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:4000";

const TASK_LABELS: Record<string, string> = {
  application_question: "Application questions",
  resume_tailoring: "Resume tailoring",
  ambiguous_match: "Ambiguous matches",
  benchmark_label: "Benchmark labelling",
};

function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export function GeminiDiagnostics() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/gemini/diagnostics`, { credentials: "include" });
      if (!res.ok) throw new Error(`API returned ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    load();
    // Polled rather than streamed: the numbers move slowly and a stale circuit
    // state is the one thing on this page that would actually mislead someone.
    const timer = window.setInterval(load, 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const act = async (path: string) => {
    setBusy(true);
    try {
      await fetch(`${API}/gemini/${path}`, { method: "POST", credentials: "include" });
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <article className="workflow-panel">
        <h2>Gemini layer</h2>
        <p className="muted">Could not load diagnostics: {error}</p>
      </article>
    );
  }
  if (!data) {
    return (
      <article className="workflow-panel">
        <h2>Gemini layer</h2>
        <p className="muted">Loading…</p>
      </article>
    );
  }

  const { metrics: m, circuit, queue } = data;
  const healthKey = data.health.toLowerCase().replace(/\s+/g, "-");

  return (
    <>
      <article className="workflow-panel dashboard-panel--wide">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Optional intelligence layer</span>
            <h2>Gemini</h2>
            <p className="muted" style={{ marginTop: "0.4rem", maxWidth: "64ch" }}>
              Gemini enriches open-ended answers, resume wording and the job matches CareerOS
              cannot settle on its own. Everything below can be zero and CareerOS still runs
              normally — deterministic matching, profile answers and submission do not depend
              on it.
            </p>
          </div>
          <span className={`gemini-health gemini-health--${healthKey}`}>
            <i aria-hidden="true" />
            {data.health}
          </span>
        </div>

        <div className="matcher-verdicts">
          <div className="matcher-verdict">
            <span className="matcher-verdict-label">Model</span>
            <strong style={{ fontSize: "0.95rem" }}>{data.model}</strong>
            <span className="muted">{data.configured ? "API key configured" : "No API key"}</span>
          </div>
          <div className={`matcher-verdict${circuit.state !== "CLOSED" ? " matcher-verdict--warn" : ""}`}>
            <span className="matcher-verdict-label">Circuit</span>
            <strong>{circuit.state}</strong>
            <span className="muted">
              {circuit.state === "OPEN"
                ? `retry in ${Math.ceil(circuit.secondsUntilRetry)}s`
                : `${circuit.consecutiveFailures} consecutive failure${circuit.consecutiveFailures === 1 ? "" : "s"}`}
            </span>
          </div>
          <div className="matcher-verdict">
            <span className="matcher-verdict-label">Queue depth</span>
            <strong>{num(queue.depth)}</strong>
            <span className="muted">
              {Object.entries(queue.byPriority).map(([name, count]) => `${name.toLowerCase()} ${count}`).join(", ")
                || `${queue.concurrency} concurrent, idle`}
            </span>
          </div>
          <div className="matcher-verdict">
            <span className="matcher-verdict-label">Cache hit rate</span>
            <strong>{percent(m.cacheHitRate)}</strong>
            <span className="muted">{num(m.cacheHits + m.dedupeHits)} served without an API call</span>
          </div>
          <div className={`matcher-verdict${m.applicationsStagedForReview > 0 ? " matcher-verdict--warn" : ""}`}>
            <span className="matcher-verdict-label">Sent to review</span>
            <strong>{num(m.applicationsStagedForReview)}</strong>
            <span className="muted">applications staged because Gemini was unavailable</span>
          </div>
          <div className="matcher-verdict">
            <span className="matcher-verdict-label">Deterministic fallbacks</span>
            <strong>{num(m.fallbacks)}</strong>
            <span className="muted">times CareerOS carried on without it</span>
          </div>
        </div>

        {/* The limits in force, because "why is this slow" is usually answered
            by the spacing between calls rather than by anything being wrong. */}
        <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.25rem" }}>
          {data.limits.concurrency} request at a time, at least{" "}
          {data.limits.minIntervalSeconds}s apart, up to {data.limits.maxAttempts} attempts;
          the circuit opens after {data.limits.failureThreshold} consecutive failures for{" "}
          {Math.round(data.limits.cooldownSeconds / 60)} minutes.
        </p>

        {circuit.state !== "CLOSED" && circuit.reason ? (
          <p className="muted gemini-circuit-reason">
            Circuit opened after: <code>{circuit.reason}</code>
          </p>
        ) : null}
      </article>

      <article className="workflow-panel dashboard-panel--wide">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Traffic</span>
            <h2>Requests and outcomes</h2>
          </div>
        </div>

        <div className="gemini-stat-grid">
          <div><span>Requests</span><strong>{num(m.requests)}</strong></div>
          <div><span>API calls</span><strong>{num(m.apiCalls)}</strong></div>
          <div><span>Success rate</span><strong>{percent(m.successRate)}</strong></div>
          <div><span>Retries</span><strong>{num(m.retries)}</strong></div>
          <div><span>429 rate limited</span><strong>{num(m.rateLimited429)}</strong></div>
          <div><span>503 unavailable</span><strong>{num(m.serverErrors503)}</strong></div>
          <div><span>404 config errors</span><strong>{num(m.configErrors404)}</strong></div>
          <div><span>Other 4xx</span><strong>{num(m.permanentErrors)}</strong></div>
          <div><span>Malformed replies</span><strong>{num(m.malformedResponses)}</strong></div>
          <div><span>Timeouts</span><strong>{num(m.timeouts)}</strong></div>
          <div><span>Blocked by circuit</span><strong>{num(m.circuitRejections)}</strong></div>
          <div><span>Latency p50</span><strong>{num(m.latencyMs.p50)}<small> ms</small></strong></div>
          <div><span>Latency p95</span><strong>{num(m.latencyMs.p95)}<small> ms</small></strong></div>
          <div><span>Tokens</span><strong>{num(m.tokens.total)}</strong></div>
          <div><span>Est. cost</span><strong>${m.estimatedCostUsd.toFixed(4)}</strong></div>
        </div>
        <p className="muted" style={{ fontSize: "0.8rem", marginTop: "0.75rem" }}>
          {m.estimatedCostNote}
        </p>
      </article>

      <article className="workflow-panel dashboard-panel--wide">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">By task</span>
            <h2>Where Gemini is being used</h2>
            <p className="muted" style={{ marginTop: "0.4rem", maxWidth: "62ch" }}>
              Priority runs top to bottom: an application being submitted is served before an
              application question, which is served before tailoring, a speculative match, and
              finally offline benchmark labelling.
            </p>
          </div>
        </div>

        <div className="matcher-tablewrap">
          <table className="matcher-table">
            <thead>
              <tr>
                <th>Task</th>
                <th style={{ textAlign: "right" }}>Requests</th>
                <th style={{ textAlign: "right" }}>Succeeded</th>
                <th style={{ textAlign: "right" }}>Cached</th>
                <th style={{ textAlign: "right" }}>Failed</th>
                <th style={{ textAlign: "right" }}>Fell back</th>
              </tr>
            </thead>
            <tbody>
              {Object.keys(m.byTask).length === 0 ? (
                <tr><td colSpan={6} className="muted">No Gemini work yet since the backend started.</td></tr>
              ) : (
                Object.entries(m.byTask).map(([task, counts]) => (
                  <tr key={task}>
                    <td>{TASK_LABELS[task] ?? task}</td>
                    <td className="num">{num(counts.requests)}</td>
                    <td className="num">{num(counts.success)}</td>
                    <td className="num">{num(counts.cacheHits)}</td>
                    <td className="num">{num(counts.failure)}</td>
                    <td className="num">{num(counts.fallbacks)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {m.recentFailures.length > 0 && (
          <>
            <p className="matcher-verdict-label" style={{ marginTop: "1.25rem" }}>Recent failures</p>
            <ul className="gemini-failures">
              {m.recentFailures.map((failure, index) => (
                <li key={`${failure.at}-${index}`}>
                  <code>{failure.at}</code>
                  <b>{failure.outcome}</b>
                  <span>{TASK_LABELS[failure.task] ?? failure.task}</span>
                  <span className="muted">{failure.detail}</span>
                </li>
              ))}
            </ul>
          </>
        )}

        <div className="gemini-actions">
          <button type="button" className="ghost-button" disabled={busy} onClick={() => act("metrics/reset")}>
            Reset counters
          </button>
          <button
            type="button"
            className="ghost-button"
            disabled={busy || circuit.state === "CLOSED"}
            onClick={() => act("circuit/close")}
            title="Use after fixing the cause, instead of waiting out the cooldown"
          >
            Close circuit now
          </button>
        </div>
      </article>
    </>
  );
}
