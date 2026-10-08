"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { CareerIcon } from "@/components/ui/career-icon";
import { getClientApiBaseUrl } from "@/lib/api";
import { H1BMark, StatusDot, statusText } from "./bits";
import { hostOf, priorityLabel, shortDate, timeAgo } from "./format";
import type { CompanyDetail, MarketCompany } from "./types";
import styles from "./markets.module.css";

const AUTOMATIC = new Set(["ATS_API", "PROPRIETARY_API", "JSON_ENDPOINT", "STATIC_HTML"]);

export function CompanyDrawer({
  marketId,
  company,
  refreshing,
  marketRunning,
  onClose,
  onRefresh,
  onViewJobs,
}: {
  marketId: string;
  company: MarketCompany;
  refreshing: boolean;
  marketRunning: boolean;
  onClose: () => void;
  onRefresh: (id: string) => void;
  onViewJobs: (companyId: string) => void;
}) {
  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [showSteps, setShowSteps] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${getClientApiBaseUrl()}/markets/${marketId}/companies/${company.id}`, { credentials: "include", cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch(() => { if (!cancelled) setDetail(null); });
    return () => { cancelled = true; };
  }, [marketId, company.id, company.career.lastAttemptAt, company.jobs.relevant]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const c = detail ?? company;
  const career = c.career;
  const jobs = c.jobs;
  const automatic = AUTOMATIC.has(career.sourceType) && career.status !== "manual";
  const tone = career.status === "failed" ? "fail" : career.status === "manual" || career.status === "degraded" ? "warn" : undefined;
  const top = (detail?.opportunities ?? []).slice(0, 6);
  const latestScanRead = Boolean(career.lastSuccessAt && career.lastSuccessAt === career.lastAttemptAt);

  // Portaled: the app shell's transformed ancestors would otherwise make the
  // fixed drawer as tall as the page, pushing its actions out of view.
  if (!mounted) return null;
  return createPortal(
    <>
      <div className={styles.scrim} onClick={onClose} aria-hidden />
      <aside className={styles.drawer} role="dialog" aria-modal="true" aria-label={`${c.name} details`}>
        <div className={styles.drawerHead} data-tone={tone}>
          <div style={{ minWidth: 0 }}>
            <div className={styles.drawerTitle}>{c.name}</div>
            <div className={styles.drawerSub}>
              #{priorityLabel(c.priority)} · {c.tierLabel || (c.tier ? `Tier ${c.tier}` : "Untiered")}
              {c.areas.length ? ` · ${c.areas.slice(0, 3).join(", ")}` : ""}
              {c.zoneLabel ? ` · ${c.zoneLabel}` : ""}
            </div>
          </div>
          <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
            <CareerIcon name="close" />
          </button>
        </div>

        <div className={styles.drawerBody}>
          {career.status === "manual" ? (
            <div className={styles.callout}>
              <strong>{statusText("manual", career.sourceType)}: CareerOS can&apos;t read this career site unattended.</strong>
              <div style={{ marginTop: ".35rem" }}>{career.failureReason || "No supported job feed was found."}</div>
              <div style={{ marginTop: ".35rem" }}>
                Last attempt {timeAgo(career.lastAttemptAt)} · Known jobs from other sources: <strong>{jobs.otherSources}</strong>
              </div>
              <div style={{ marginTop: ".35rem", color: "var(--muted)" }}>
                CareerOS will continue showing jobs discovered through other sources.
              </div>
            </div>
          ) : career.status === "failed" || career.status === "degraded" ? (
            <div className={styles.callout} data-tone={career.status === "failed" ? "fail" : undefined}>
              <strong>{career.status === "failed" ? "Last scan failed" : latestScanRead ? "Counts may be incomplete" : "Last scan partly failed"}</strong>
              <div style={{ marginTop: ".35rem" }}>{career.failureReason || "The source did not answer."}</div>
              {latestScanRead ? null : (
                <div style={{ marginTop: ".35rem" }}>
                  Last success {timeAgo(career.lastSuccessAt)}. Counts below are from the last good scan, not zero.
                </div>
              )}
            </div>
          ) : null}

          <section className={styles.section}>
            <h4>Opportunities</h4>
            <div className={styles.miniStats}>
              <div className={styles.miniStat} data-accent={jobs.relevant > 0}>
                <b>{jobs.relevant}</b><span>relevant in market</span>
              </div>
              <div className={styles.miniStat}>
                <b>{jobs.highMatch}</b><span>≥80% match</span>
              </div>
              <div className={styles.miniStat}>
                <b>{jobs.state === "known" ? jobs.totalOpen ?? "—" : "?"}</b>
                <span>{jobs.scope === "search" ? "found in search" : "open postings"}</span>
              </div>
            </div>
            {jobs.state === "known" ? (
              <p className={styles.note}>
                {jobs.inMarket ?? 0} in the market area · {jobs.scopeLabel}
                {jobs.truncated ? " · more postings exist than were read" : ""}
                {jobs.otherSources ? ` · ${jobs.otherSources} relevant from other sources` : ""}
              </p>
            ) : null}
            {top.length ? (
              <div className={styles.jobList} style={{ marginTop: ".6rem" }}>
                {top.map((o) => (
                  <div key={o.id} className={styles.jobItem}>
                    <span className={styles.score} data-band={o.score >= 80 ? "high" : o.score >= 60 ? "mid" : undefined}>{o.score}</span>
                    <div style={{ minWidth: 0 }}>
                      <a href={o.url} target="_blank" rel="noreferrer">{o.title}</a>
                      <div className={styles.jobItemMeta}>
                        {o.areas.join(", ") || o.location} · {o.official ? "official" : o.source ?? "other source"}
                        {o.isNew ? " · new" : ""}
                      </div>
                    </div>
                    <span className={styles.jobItemMeta}>{shortDate(o.postedAt)}</span>
                  </div>
                ))}
              </div>
            ) : detail && jobs.relevant === 0 ? (
              <p className={styles.note}>No relevant senior engineering roles in the market right now.</p>
            ) : null}
          </section>

          <section className={styles.section}>
            <h4>H1B</h4>
            <dl className={styles.kv}>
              <dt>History</dt><dd><H1BMark strength={c.h1b.strength} h1b={c.h1b} /></dd>
              {c.h1b.localLcaCount != null ? (<><dt>Local LCAs</dt><dd>{c.h1b.localLcaCount}{c.h1b.lcaArea ? ` (${c.h1b.lcaArea})` : ""}</dd></>) : null}
              {c.h1b.activity ? (<><dt>Activity</dt><dd>{c.h1b.activity}</dd></>) : null}
              {c.h1b.evidence ? (<><dt>Evidence</dt><dd>{c.h1b.evidence}</dd></>) : null}
              {c.h1b.evidenceUrls.map((u) => (
                <span key={u} style={{ display: "contents" }}><dt>Link</dt><dd><a href={u} target="_blank" rel="noreferrer">{hostOf(u)}</a></dd></span>
              ))}
            </dl>
            <p className={styles.note}>{c.h1b.note}</p>
          </section>

          <section className={styles.section}>
            <h4>Career source</h4>
            <dl className={styles.kv}>
              <dt>Status</dt><dd><span className={styles.status}><StatusDot status={career.status} />{statusText(career.status, career.sourceType)}</span></dd>
              <dt>Source</dt><dd>{career.label}{career.method ? ` · ${career.method.replace(/_/g, " ")}` : ""}{career.confidence ? ` · ${Math.round(career.confidence * 100)}% confidence` : ""}</dd>
              <dt>Career site</dt>
              <dd>{career.url ? <a href={career.url} target="_blank" rel="noreferrer">{career.url}</a> : "None verified"}{career.urlSource && career.urlSource !== "seed" ? ` (${career.urlSource.replace(/_/g, " ")})` : ""}</dd>
              {career.evidence ? (<><dt>Evidence</dt><dd>{career.evidence}</dd></>) : null}
              <dt>Last success</dt><dd>{career.lastSuccessAt ? `${timeAgo(career.lastSuccessAt)}` : "never"}</dd>
              <dt>Last attempt</dt><dd>{career.lastAttemptAt ? timeAgo(career.lastAttemptAt) : "never"}{career.httpStatus ? ` · HTTP ${career.httpStatus}` : ""}</dd>
              {career.sourceChange ? (<><dt>Changed</dt><dd>{career.sourceChange.from} → {career.sourceChange.to}</dd></>) : null}
              {career.rejectedUrl ? (<><dt>Rejected</dt><dd>{career.rejectedUrl} (aggregator, not official)</dd></>) : null}
            </dl>
            {detail?.career.detectionSteps?.length ? (
              <>
                <button type="button" className={styles.clear} style={{ marginTop: ".5rem" }} onClick={() => setShowSteps((v) => !v)}>
                  {showSteps ? "Hide" : "Show"} detection trail ({detail.career.detectionSteps.length} steps)
                </button>
                {showSteps ? (
                  <div className={styles.steps} style={{ marginTop: ".4rem" }}>
                    {detail.career.detectionSteps.map((s, i) => (
                      <span key={i}><b>{s.step}</b> {s.outcome}{Object.entries(s).filter(([k]) => k !== "step" && k !== "outcome").map(([k, v]) => ` · ${k}: ${String(v)}`).join("")}</span>
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}
          </section>

          {c.whyFits || c.notes ? (
            <section className={styles.section}>
              <h4>Why it fits</h4>
              {c.whyFits ? <p className={styles.note} style={{ color: "var(--text-secondary)", fontSize: "var(--text-xs)" }}>{c.whyFits}</p> : null}
              {c.notes ? <p className={styles.note}>{c.notes}</p> : null}
            </section>
          ) : null}

          <section className={styles.section}>
            <h4>Provenance</h4>
            <dl className={styles.kv}>
              <dt>Imported from</dt>
              <dd>{Object.values(c.provenance.seeds).map((s) => `${s.file}, row ${s.row}`).join("; ") || c.provenance.source || "—"}</dd>
              <dt>Imported</dt><dd>{c.provenance.sourceImportedAt ? timeAgo(c.provenance.sourceImportedAt) : "—"}</dd>
            </dl>
          </section>
        </div>

        <div className={styles.drawerActions}>
          {jobs.relevant > 0 ? (
            <button type="button" className="btn btn-sm" onClick={() => onViewJobs(c.id)}>View all {jobs.relevant} jobs</button>
          ) : null}
          {career.url ? (
            <a className="btn btn-sm" href={career.url} target="_blank" rel="noreferrer">Open Career Site ↗</a>
          ) : null}
          <button
            type="button"
            className="btn btn-sm"
            disabled={refreshing || marketRunning}
            title={marketRunning ? "A market refresh is running" : undefined}
            onClick={() => onRefresh(c.id)}
          >
            {refreshing ? "Refreshing…" : automatic ? "↻ Refresh" : "↻ Retry detection"}
          </button>
        </div>
      </aside>
    </>,
    document.body,
  );
}
