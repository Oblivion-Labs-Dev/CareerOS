"use client";

import { useEffect, useMemo, useState } from "react";
import { CountUp } from "@/components/count-up";
import { useRouter } from "next/navigation";
import { getAutopilotJobs } from "@/lib/application-assistant-api";
import styles from "./application-insights.module.css";

/** Every status the API can return, fetched in one request and sliced locally. */
const ALL_STATUSES =
  "QUEUED,APPLYING,SUBMITTED,NEEDS_REVIEW,STAGED,FAILED,SKIPPED,INELIGIBLE";

type Job = {
  status?: string;
  company?: string;
  title?: string;
  location?: string;
  matchScore?: number | null;
  ineligibilityReason?: string;
};

const OUTCOMES = [
  { key: "SUBMITTED", name: "Submitted", color: "var(--success)" },
  { key: "REVIEW", name: "Needs answer", color: "var(--warning)" },
  { key: "QUEUED", name: "Queued", color: "var(--accent)" },
  { key: "FAILED", name: "Failed", color: "var(--danger)" },
  { key: "SKIPPED", name: "Skipped", color: "var(--muted)" },
  { key: "INELIGIBLE", name: "Ineligible", color: "var(--accent-tertiary)" },
] as const;

/** Where each outcome links on the Applications tab, so a bar is a way in. */
const OUTCOME_TAB: Record<string, string> = {
  SUBMITTED: "submitted",
  REVIEW: "review",
  QUEUED: "queued",
  FAILED: "failed",
  SKIPPED: "skipped",
  INELIGIBLE: "applications",
};

const BLOCKER_NAMES: Record<string, string> = {
  REQUIRES_US_CITIZENSHIP: "Needs U.S. citizenship",
  NO_VISA_SPONSORSHIP: "No visa sponsorship",
  OUTSIDE_UNITED_STATES: "Outside the U.S.",
  POSTING_EXPIRED: "Posting was pulled",
  NOT_A_REAL_POSTING: "Not a real posting",
  DUPLICATE_APPLICATION: "Already applied",
};

const SEATTLE_KEYS = ["seattle", "bellevue", "redmond", "kirkland", ", wa", "washington"];

const ABOVE_SENIOR = ["staff", "principal", "distinguished", "fellow", "architect",
  "director", "head of", "vp ", "vice president"];
const SENIOR_KEYS = ["senior software engineer", "sr. software engineer",
  "sr software engineer", "senior swe"];

/** Same vocabulary the API ranks with, so the chart agrees with the queue order. */
function levelOf(title?: string): "Senior" | "Above senior" | "Other" {
  const t = (title || "").toLowerCase();
  const above = ABOVE_SENIOR.some((k) => t.includes(k));
  const senior = SENIOR_KEYS.some((k) => t.includes(k));
  if (senior && !above) return "Senior";
  if (above) return "Above senior";
  return "Other";
}

const LEVEL_COLORS: Record<string, string> = {
  Senior: "var(--success)",
  "Above senior": "var(--accent-tertiary)",
  Other: "var(--muted)",
};

const BANDS = [
  { name: "80-100", min: 80, color: "var(--success)" },
  { name: "60-79", min: 60, color: "var(--accent)" },
  { name: "40-59", min: 40, color: "var(--warning)" },
  { name: "0-39", min: 0, color: "var(--danger)" },
];

function bucket(status?: string): string {
  if (status === "NEEDS_REVIEW" || status === "STAGED") return "REVIEW";
  if (status === "APPLYING") return "QUEUED";
  return status || "QUEUED";
}

export function ApplicationInsights() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAutopilotJobs(ALL_STATUSES, 1000)
      .then((res) => !cancelled && setJobs(res.jobs || []))
      .catch(() => !cancelled && setJobs([]));
    return () => {
      cancelled = true;
    };
  }, []);

  const data = useMemo(() => {
    if (!jobs) return null;
    const total = jobs.length;

    const counts: Record<string, number> = {};
    for (const j of jobs) {
      const b = bucket(j.status);
      counts[b] = (counts[b] || 0) + 1;
    }

    const submitted = counts.SUBMITTED || 0;
    const ineligible = counts.INELIGIBLE || 0;
    const skipped = counts.SKIPPED || 0;
    // "Attempted" = everything Autopilot actually opened a browser for: the
    // ineligible and filtered-out postings were never applyable in the first
    // place, so counting them would understate the real success rate.
    const attempted = Math.max(0, total - ineligible - skipped);

    const companies = new Map<string, number>();
    for (const j of jobs) {
      if (j.status !== "SUBMITTED") continue;
      const c = (j.company || "").trim();
      if (!c) continue;
      const name = c.charAt(0).toUpperCase() + c.slice(1);
      companies.set(name, (companies.get(name) || 0) + 1);
    }
    const topCompanies = [...companies.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);

    const blockers = new Map<string, number>();
    for (const j of jobs) {
      if (j.status !== "INELIGIBLE") continue;
      const r = j.ineligibilityReason || "OTHER";
      blockers.set(r, (blockers.get(r) || 0) + 1);
    }
    const topBlockers = [...blockers.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);

    const submittedJobs = jobs.filter((j) => j.status === "SUBMITTED");
    const inSeattle = submittedJobs.filter((j) =>
      SEATTLE_KEYS.some((k) => (j.location || "").toLowerCase().includes(k)),
    ).length;

    const levels = new Map<string, number>();
    for (const j of submittedJobs) {
      const l = levelOf(j.title);
      levels.set(l, (levels.get(l) || 0) + 1);
    }

    const bands = BANDS.map((b) => ({ ...b, count: 0 }));
    for (const j of submittedJobs) {
      const s = Number(j.matchScore || 0);
      const hit = bands.find((b) => s >= b.min);
      if (hit) hit.count += 1;
    }

    return {
      levels,
      bands,
      total,
      counts,
      submitted,
      attempted,
      ineligible,
      topCompanies,
      topBlockers,
      inSeattle,
      submittedTotal: submittedJobs.length,
    };
  }, [jobs]);

  if (!data) {
    return <p className={styles.empty}>Loading application insights…</p>;
  }

  if (data.total === 0) {
    return (
      <p className={styles.empty}>
        No applications yet. Start a run on the Autopilot page to fill this in.
      </p>
    );
  }

  const mix = OUTCOMES.map((o) => ({ ...o, count: data.counts[o.key] || 0 })).filter(
    (o) => o.count > 0,
  );
  const mixTotal = mix.reduce((s, o) => s + o.count, 0) || 1;

  const submitRate = data.attempted
    ? Math.round((data.submitted / data.attempted) * 100)
    : 0;
  const seattleShare = data.submittedTotal
    ? Math.round((data.inSeattle / data.submittedTotal) * 100)
    : 0;

  const funnel = [
    { name: "Evaluated", value: data.total, color: "var(--accent)" },
    { name: "Applyable", value: data.attempted, color: "var(--accent-tertiary)" },
    { name: "Submitted", value: data.submitted, color: "var(--success)" },
  ];
  const funnelMax = Math.max(1, ...funnel.map((f) => f.value));

  const levelRows = [...data.levels.entries()].sort((a, b) => b[1] - a[1]);
  const maxCompany = Math.max(1, ...data.topCompanies.map(([, n]) => n));
  const maxBlocker = Math.max(1, ...data.topBlockers.map(([, n]) => n));

  return (
    <div className={`${styles.grid} ${styles.gridThree}`}>
      {/* ── Outcome mix ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>Outcome mix</span>
          <span className={styles.cardNote}>{data.total} tracked</span>
        </div>

        <div className={styles.mixBar} role="img" aria-label="Application outcomes by share">
          {mix.map((o) => (
            <button
              key={o.key}
              type="button"
              className={styles.mixSeg}
              style={{ width: `${(o.count / mixTotal) * 100}%`, background: o.color }}
              title={`${o.name}: ${o.count}`}
              aria-label={`${o.name}: ${o.count}`}
              onClick={() => router.push(`/applications?tab=${OUTCOME_TAB[o.key] || "applications"}`)}
            />
          ))}
        </div>

        <div className={styles.legend}>
          {mix.map((o) => (
            <span key={o.key} className={styles.legendRow}>
              <span className={styles.legendDot} style={{ background: o.color }} />
              <span className={styles.legendName}>{o.name}</span>
              <span className={styles.legendValue}><CountUp value={o.count} locale /></span>
              <span className={styles.legendPct}>
                <CountUp value={Math.round((o.count / mixTotal) * 100)} suffix="%" />
              </span>
            </span>
          ))}
        </div>
      </section>

      {/* ── Funnel ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>From posting to submitted</span>
          <span className={styles.cardNote}>{submitRate}% of applyable</span>
        </div>

        <div className={styles.funnel}>
          {funnel.map((stage, i) => {
            const prev = i > 0 ? funnel[i - 1].value : null;
            const drop = prev && prev > 0 ? Math.round((stage.value / prev) * 100) : null;
            return (
              <div key={stage.name} className={styles.stage}>
                <div className={styles.stageTop}>
                  <span className={styles.stageName}>{stage.name}</span>
                  <span className={styles.stageValue}><CountUp value={stage.value} locale delayMs={i * 80} /></span>
                </div>
                <div className={styles.stageTrack}>
                  <div
                    className={styles.stageFill}
                    style={
                      {
                        width: `${Math.max(2, (stage.value / funnelMax) * 100)}%`,
                        "--stage-color": stage.color,
                      } as React.CSSProperties
                    }
                  />
                </div>
                {drop !== null && (
                  <span className={styles.stageDrop}><CountUp value={drop} suffix="%" delayMs={i * 80} /> carried through</span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Seattle share ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>Seattle share</span>
          <span className={styles.cardNote}>of submitted</span>
        </div>
        <div>
          <div className={styles.splitValue}><CountUp value={seattleShare} suffix="%" /></div>
          <p className={styles.splitCaption}>
            {data.inSeattle} of {data.submittedTotal} submitted applications are in the
            Seattle area. The rest are elsewhere in the United States.
          </p>
        </div>
        <div className={styles.mixBar} role="img" aria-label="Seattle share of submitted applications">
          <span
            className={styles.mixSeg}
            style={{ width: `${seattleShare}%`, background: "var(--accent)" }}
          />
          <span
            className={styles.mixSeg}
            style={{ width: `${100 - seattleShare}%`, background: "color-mix(in srgb, var(--muted) 40%, transparent)" }}
          />
        </div>
      </section>

      {/* ── Companies ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>Most applied to</span>
          <span className={styles.cardNote}>submitted</span>
        </div>
        {data.topCompanies.length === 0 ? (
          <p className={styles.empty}>Nothing submitted yet.</p>
        ) : (
          <div className={styles.rankList}>
            {data.topCompanies.map(([name, n]) => (
              <div key={name} className={styles.rankRow}>
                <span className={styles.rankLabel}>{name}</span>
                <span className={styles.rankCount}>{n}</span>
                <span className={styles.rankTrack}>
                  <span
                    className={styles.rankFill}
                    style={
                      {
                        width: `${(n / maxCompany) * 100}%`,
                        "--rank-color": "var(--success)",
                      } as React.CSSProperties
                    }
                  />
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Blockers ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>Why some never applied</span>
          <span className={styles.cardNote}>{data.ineligible} ineligible</span>
        </div>
        {data.topBlockers.length === 0 ? (
          <p className={styles.empty}>Nothing blocked. Every posting was applyable.</p>
        ) : (
          <div className={styles.rankList}>
            {data.topBlockers.map(([reason, n]) => (
              <div key={reason} className={styles.rankRow}>
                <span className={styles.rankLabel}>
                  {BLOCKER_NAMES[reason] || "Other"}
                </span>
                <span className={styles.rankCount}>{n}</span>
                <span className={styles.rankTrack}>
                  <span
                    className={styles.rankFill}
                    style={
                      {
                        width: `${(n / maxBlocker) * 100}%`,
                        "--rank-color": "var(--accent-tertiary)",
                      } as React.CSSProperties
                    }
                  />
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Needs you ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>Waiting on you</span>
          <span className={styles.cardNote}>blocking submission</span>
        </div>
        <div>
          <div className={styles.splitValue}>{data.counts.REVIEW || 0}</div>
          <p className={styles.splitCaption}>
            {(data.counts.REVIEW || 0) === 0
              ? "Nothing needs your answer. Autopilot can submit everything in the queue."
              : "Applications Autopilot filled in but would not submit without an answer from you."}
          </p>
        </div>
        {(data.counts.REVIEW || 0) > 0 && (
          <button
            type="button"
            className={styles.rankLabel}
            style={{
              textAlign: "left",
              color: "var(--accent)",
              fontWeight: 700,
              cursor: "pointer",
              background: "none",
              border: "none",
              padding: 0,
            }}
            onClick={() => router.push("/applications?tab=review")}
          >
            Answer them now
          </button>
        )}
      </section>

      {/* ── Level mix ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>Level applied at</span>
          <span className={styles.cardNote}>submitted</span>
        </div>
        {levelRows.length === 0 ? (
          <p className={styles.empty}>Nothing submitted yet.</p>
        ) : (
          <>
            <div className={styles.mixBar} role="img" aria-label="Seniority of submitted applications">
              {levelRows.map(([name, n]) => (
                <span
                  key={name}
                  className={styles.mixSeg}
                  style={{
                    width: `${(n / data.submittedTotal) * 100}%`,
                    background: LEVEL_COLORS[name],
                  }}
                  title={`${name}: ${n}`}
                />
              ))}
            </div>
            <div className={styles.legend}>
              {levelRows.map(([name, n]) => (
                <span key={name} className={styles.legendRow}>
                  <span className={styles.legendDot} style={{ background: LEVEL_COLORS[name] }} />
                  <span className={styles.legendName}>{name}</span>
                  <span className={styles.legendValue}>{n}</span>
                  <span className={styles.legendPct}>
                    {Math.round((n / data.submittedTotal) * 100)}%
                  </span>
                </span>
              ))}
            </div>
          </>
        )}
      </section>

      {/* ── Match quality ── */}
      <section className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.cardTitle}>Match quality</span>
          <span className={styles.cardNote}>of submitted</span>
        </div>
        {data.submittedTotal === 0 ? (
          <p className={styles.empty}>Nothing submitted yet.</p>
        ) : (
          <div className={styles.rankList}>
            {data.bands.map((b) => (
              <div key={b.name} className={styles.rankRow}>
                <span className={styles.rankLabel}>{b.name}% match</span>
                <span className={styles.rankCount}>{b.count}</span>
                <span className={styles.rankTrack}>
                  <span
                    className={styles.rankFill}
                    style={
                      {
                        width: `${(b.count / Math.max(1, data.submittedTotal)) * 100}%`,
                        "--rank-color": b.color,
                      } as React.CSSProperties
                    }
                  />
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
