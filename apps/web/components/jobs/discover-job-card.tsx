"use client";
import {useSurfaceDepth} from "@/hooks/use-surface-depth";
import {triageSignals} from "@/lib/inbox-triage";
import {JobMetaBadges} from "./job-meta-badges";
import type {DiscoverJob} from "./discover-job";
import styles from "./browse-jobs.module.css";

type Props = {job: DiscoverJob; selected: boolean; shortlisted: boolean; busy: boolean; queued: boolean;
  fit?: {verdict: string; overallScore: number; legitimacy?: string};
  onSelect:()=>void; onShortlist:()=>void; onHide:()=>void; onDetails:()=>void; onQueue:()=>void; onApply:()=>void};

export function DiscoverJobCard({job,selected,shortlisted,busy,queued,fit,onSelect,onShortlist,onHide,onDetails,onQueue,onApply}:Props) {
  const surface = useSurfaceDepth();
  const score = typeof job.relevancyScore === "number" && Number.isFinite(job.relevancyScore) ? Math.max(0,Math.min(100,Math.round(job.relevancyScore))) : null;
  const signals = triageSignals(job);
  const gap = job.gapAnalysis?.gapPercent;
  return <article ref={surface} className={styles.card} data-selected={selected} data-job-id={job.id} role="listitem">
    <div className={styles.identity}><span className={styles.monogram} aria-hidden="true">{(job.companyName || "?").split(/\s+/).slice(0,2).map(word=>word[0]).join("")}</span><div><strong>{job.companyName || "Unknown company"}</strong><small>{signals.ats === "other" ? "CAREER OPPORTUNITY" : signals.ats.toUpperCase()}</small></div><input type="checkbox" checked={selected} onChange={onSelect} aria-label={`Select ${job.title} at ${job.companyName} for batch preparation`}/></div>
    <h3 className={styles.title}><a href={job.url} target="_blank" rel="noopener noreferrer">{job.title}<span aria-hidden="true">↗</span></a></h3>
    <p className={styles.location}>{job.location || "Location not listed"}</p>
    <div className={styles.fitRow}><div className={styles.dial} aria-label={score===null ? "Match not scored" : `${score}% profile match`}><svg viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="20"/><circle cx="24" cy="24" r="20" pathLength="100" strokeDasharray={`${score ?? 0} 100`}/></svg><strong>{score ?? "—"}</strong></div><div><strong>{score===null ? "Awaiting score" : score>=75 ? "Strong profile fit" : score>=50 ? "Potential fit" : "Explore the fit"}</strong><small>{job.freshness?.label || "Posting date not recorded"}</small></div><button onClick={onDetails}>Fit details{typeof gap === "number" && Number.isFinite(gap) ? ` · ${Math.round(gap)}% gap` : " ↗"}</button></div>
    <div className={styles.skills}>{job.keywordsMatched?.length ? job.keywordsMatched.slice(0,3).map(skill=><span key={skill}>{skill}</span>) : <span>Skills not assessed yet</span>}{job.salaryRange && <span>{job.salaryRange}</span>}</div>
    <details className={styles.meta}><summary>Role details <span>+</span></summary><JobMetaBadges employmentType={job.employmentType} h1bStatus={job.h1bStatus} h1bLabel={job.h1bLabel} h1bReason={job.h1bReason} h1bSignals={job.h1bSignals}/>{signals.seniority && <p>{signals.seniority}</p>}{fit && <p>{fit.verdict} · {fit.overallScore} overall fit{fit.legitimacy === "caution" ? " · Review posting legitimacy" : ""}</p>}</details>
    <footer className={styles.footer}><div><button onClick={onShortlist} aria-pressed={shortlisted} aria-label={`${shortlisted ? "Remove from" : "Add to"} shortlist: ${job.title}`} title={shortlisted ? "Remove from shortlist" : "Save to shortlist"}>{shortlisted ? "★" : "☆"}</button><button onClick={onHide} aria-label={`Hide ${job.title} at ${job.companyName}`} title="Hide this posting">×</button></div><div><button onClick={onQueue} disabled={busy || queued}>{queued ? "Queued" : "Add to queue"}</button><button className={styles.apply} onClick={onApply} disabled={busy || queued} title="Start an Autopilot application">Apply ↗</button></div></footer>
  </article>;
}
