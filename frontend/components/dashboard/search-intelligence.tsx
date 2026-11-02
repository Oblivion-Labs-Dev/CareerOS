"use client";

import { useEffect, useState } from "react";
import { CountUp } from "@/components/count-up";
import Link from "next/link";
import { getAutopilotJobsPage } from "@/lib/application-assistant-api";
import type { AutopilotJobRow } from "../application-assistant/autopilot/job-types";
import styles from "./search-intelligence.module.css";

export function SearchIntelligence() {
  const [jobs, setJobs] = useState<AutopilotJobRow[] | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [updated, setUpdated] = useState("");
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const rows: AutopilotJobRow[] = [];
        let offset = 0;
        while (true) {
          const result = await getAutopilotJobsPage({ limit: 1000, offset });
          if (!active) return;
          if (!result.success) throw new Error("Could not load applications");
          rows.push(...result.jobs);
          if (!result.hasMore) break;
          if (!result.jobs.length) throw new Error("Incomplete application data");
          offset += result.jobs.length;
        }
        setJobs([...new Map(rows.map(job => [job.id, job])).values()]);
        setUpdated(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
        setError(false);
      } catch { if (active) setError(true); }
    }
    void load();
    const timer = setInterval(() => void load(), 60000);
    return () => { active = false; clearInterval(timer); };
  }, [refresh]);
  const queued = jobs?.filter(job => job.status === "QUEUED") || [];
  const review = jobs?.filter(job => ["NEEDS_REVIEW", "STAGED"].includes(job.status || "")) || [];
  const scored = queued.filter(job => typeof job.matchScore === "number" && Number.isFinite(job.matchScore));
  const strong = scored.filter(job => job.matchScore! >= 80).length;
  const submitted = jobs?.filter(job => job.status === "SUBMITTED") || [];
  const companies = new Set(submitted.map(job => job.company?.trim().toLowerCase()).filter(Boolean)).size;
  const ages = queued.map(job => job.queuedAt ? Date.parse(job.queuedAt) : NaN).filter(Number.isFinite);
  const oldest = ages.length ? Math.max(0, Math.floor((Date.now() - Math.min(...ages)) / 86400000)) : null;
  const metrics = [
    { label: "Strong matches ready", value: strong, suffix: "", note: `${queued.length} queued · ${scored.length} scored`, href: "/applications?tab=queued", tone: "green" },
    { label: "Needs your attention", value: review.length, suffix: "", note: `${review.reduce((sum, job) => sum + (job.pendingQuestions?.length || 0), 0)} pending questions`, href: "/applications?tab=review", tone: "gold" },
    { label: "Companies reached", value: companies, suffix: "", note: "Distinct companies with submitted applications", href: "/applications?tab=submitted", tone: "blue" },
    // Days, so the figure carries a unit; null when nothing is queued.
    { label: "Oldest queued role", value: oldest, suffix: "d", note: "Time since entering the queue", href: "/applications?tab=queued", tone: "rose" },
  ];
  return <section className={styles.section} aria-label="Search intelligence">
    <div className={styles.heading}><h2>Your search, at a glance</h2><button onClick={() => setRefresh(value => value + 1)}>Refresh ↻</button></div>
    <p className={styles.note} role="status">{error ? "Could not refresh application data. Any previous values are retained." : updated ? `Updated ${updated} · All ${jobs?.length} application records · Refreshes every minute` : "Loading application data…"}</p>
    <div className={styles.grid}>{metrics.map((metric, index) => <Link href={metric.href} key={metric.label} className={styles.metric} data-tone={metric.tone}>
      <span className={styles.label}>{metric.label}<span aria-hidden="true">↗</span></span><strong><CountUp value={jobs ? metric.value : null} suffix={metric.suffix} locale delayMs={index * 70} /></strong><span className={styles.note}>{jobs ? metric.note : "Waiting for backend"}</span>
    </Link>)}</div>
    <div className={styles.readiness}><div><h3>Queue readiness</h3><p>{jobs ? `${strong} roles meet the 80% match threshold. ${queued.filter(job => Boolean(job.resumeFileUsed)).length} queued roles have a recorded resume file.` : "Waiting for application records."}</p></div><div className={styles.track} role="img" aria-label={`${strong} of ${queued.length} queued roles meet the 80% match threshold`}><span className={styles.trackFill} style={{ width: `${queued.length ? strong / queued.length * 100 : 0}%` }} /></div><Link href="/applications?tab=queued">Review the queue →</Link></div>
  </section>;
}
