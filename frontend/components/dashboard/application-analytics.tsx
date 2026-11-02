"use client";

import { useEffect, useMemo, useState } from "react";
import { useCareerProgress } from "@/components/career-progress/progress-provider";
import Link from "next/link";
import { CountUp } from "@/components/count-up";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import styles from "./application-analytics.module.css";

type Kind = "submissions" | "responses" | "interviews";
type Activity = {kind: Kind; at: string; id: string; company: string; title: string};
type Outcomes = {totalSubmitted: number; awaitingConfirmation: number; cohortSize: number; linkedRecords: number; responses: number; interviews: number; medianResponseDays: number | null; datedSubmissions: number; events: Activity[]; windowDays: number; attention: {label: string; count: number; href: string}[]};
const localDay = (date: Date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;

export function ApplicationAnalytics({refreshKey = 0}: {refreshKey?: number}) {
  const {data: progress} = useCareerProgress();
  const [data, setData] = useState<Outcomes | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  const [kind, setKind] = useState<Kind>("submissions");
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    fetch("/api/backend/tracker/summary", {signal: controller.signal, cache: "no-store"})
      .then(async response => {if (!response.ok) throw new Error(); const value = await response.json(); if (!value.outcomes) throw new Error(); return value.outcomes as Outcomes;})
      .then(setData).catch(() => {if (!controller.signal.aborted) setError(true);});
    return () => controller.abort();
  }, [refreshKey, revision]);
  const days = useMemo(() => Array.from({length: 14}, (_, index) => {
    const date = new Date(); date.setDate(date.getDate() - 13 + index);
    const key = localDay(date);
    const events = (data?.events || []).filter(event => event.kind === kind && localDay(new Date(event.at)) === key);
    return {key, events, label: date.toLocaleDateString(undefined, {month: "numeric", day: "numeric"})};
  }), [data, kind]);
  const max = Math.max(1, ...days.map(day => day.events.length));
  const selectedDay = days.find(day => day.key === selected);
  const rate = (count: number) => data?.cohortSize ? `${Math.round(count / data.cohortSize * 100)}%` : "—";
  return <div className={styles.wrap}>
    {error && <p role="alert">Activity could not be refreshed. {data ? "Showing the last loaded snapshot." : "Check your connection."} <button onClick={() => setRevision(n => n + 1)}>Retry</button></p>}
    <section className={styles.chartPanel} aria-label="Application activity">
      <div className={styles.chartHead}><div><h2 className={styles.chartTitle}>Applications per day</h2><p className={styles.chartSubtitle}>Last 14 days · Your local time · Select a day to explore</p></div><div className={styles.metricSwitch}>{(["submissions", "responses", "interviews"] as Kind[]).map(value => <button key={value} aria-pressed={kind === value} onClick={() => {setKind(value); setSelected(null);}}>{value}</button>)}</div></div>
      {Boolean(progress?.records.bestWeekCount) && <p className={styles.personalBest}><span>✧ PERSONAL BEST</span> {progress!.records.bestWeekCount} confirmed in a week <small>· week of {progress!.records.bestWeek} · {progress!.preferences.timezone}</small></p>}
      {!data ? <WorkspaceLoading label="Loading application activity…" /> : <div className={styles.chart}>{days.map((day,index) => <button type="button" key={`${kind}-${day.key}`} className={`${styles.barCol} ${index === 13 ? styles["barCol--today"] : ""}`} aria-pressed={selected === day.key} aria-label={`${day.events.length} ${kind} on ${day.label}`} onClick={() => setSelected(selected === day.key ? null : day.key)}><span className={styles.barCount}>{day.events.length ? <CountUp value={day.events.length} durationMs={650} /> : ""}</span><div className={styles.barTrack}><div className={styles.bar} style={{height: `${day.events.length/max*100}%`, minHeight: day.events.length ? undefined : 0, animationDelay: `${index*30}ms`}} /></div><span className={styles.barLabel}>{day.label}</span></button>)}{days.every(day => !day.events.length) && <span className={styles.chartEmpty}>No dated {kind} recorded in this window</span>}</div>}
      {data && <p className={styles.chartSubtitle}>{kind === "submissions" ? `${data.datedSubmissions} of ${data.totalSubmitted} submitted records have a submission date. Status alone is not confirmation.` : "Only dated events on explicitly linked tracker records appear. Missing dates are not treated as zero outcomes."}</p>}
      {selectedDay && <div className={styles.drilldown} aria-live="polite"><strong>{selectedDay.label} · {selectedDay.events.length} recorded {kind}</strong>{selectedDay.events.length ? selectedDay.events.map(event => <Link key={`${event.id}-${event.at}`} href={`/applications?tab=submitted&job=${encodeURIComponent(event.id)}`}>{event.company || "Unknown company"}<span>{event.title || "Untitled role"} ↗</span></Link>) : <p>No dated events recorded for this day.</p>}</div>}
    </section>
    {data && <>
      <section className={styles.attention} aria-label="Needs attention"><h3>Needs attention</h3>{data.attention.filter(item => item.count > 0).map(item => <Link key={item.label} href={item.href}><strong>{item.count}</strong><span>{item.label}</span><span aria-hidden="true">↗</span></Link>)}{data.attention.every(item => !item.count) && <p>No pending items in the recorded data.</p>}</section>
      <div className={styles.statRow}>{[
        {label: "Recorded submissions", value: data.totalSubmitted.toLocaleString(), note: "All time · Autopilot status", tone: "accent"},
        {label: "Recorded response rate", value: data.responses ? rate(data.responses) : "—", note: `${data.responses} dated replies / ${data.cohortSize} submissions in 30 days`, tone: "cyan"},
        {label: "Recorded interview rate", value: data.interviews ? rate(data.interviews) : "—", note: `${data.interviews} dated interviews / ${data.cohortSize} submissions in 30 days`, tone: "violet"},
        {label: "Median time to reply", value: data.medianResponseDays === null ? "—" : `${data.medianResponseDays}d`, note: `${data.responses} dated response pairs · 30-day submission cohort`, tone: "success"},
        {label: "Awaiting confirmation", value: String(data.awaitingConfirmation), note: "Submitted status without specific ATS evidence", tone: "amber"},
      ].map(metric => <div key={metric.label} className={styles.statTile} data-tone={metric.tone}><span className={styles.statLabel}>{metric.label}</span><strong className={styles.statValue}>{metric.value}</strong><p className={styles.statSub}>{metric.note}</p></div>)}</div>
      <p className={styles.chartSubtitle}>Outcome coverage: {data.linkedRecords} of {data.cohortSize} submissions in the last 30 days have linked tracker records. Rates reflect recorded dated events only; — means insufficient dated evidence, not no employer response.</p>
    </>}
  </div>;
}
