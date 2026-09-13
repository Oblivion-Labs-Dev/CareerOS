import { useEffect, useState } from "react";
import Link from "next/link";
import { getAutopilotJobsPage } from "@/lib/application-assistant-api";
import type { AutopilotJobRow } from "./job-types";
import { statusView } from "./job-presentation";
import styles from "./control-center.module.css";

export function RecentSubmissions() {
  const [jobs, setJobs] = useState<AutopilotJobRow[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    let busy = false;
    async function load() {
      if (busy) return;
      busy = true;
      try {
        const result = await getAutopilotJobsPage({ status: "SUBMITTED", sortBy: "submittedAt", sortDir: "desc", limit: 3 });
        if (!result.success) throw new Error("Unavailable");
        if (active) { setJobs(result.jobs); setError(false); }
      } catch { if (active) setError(true); }
      finally { busy = false; }
    }
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  if(jobs?.length === 0 && !error) return null;
  return <section className={styles.recentSubmissions} aria-label="Latest three submissions">
    <div className={styles.panelHead}><span className={styles.panelTitle}>Latest submissions</span><Link href="/applications?tab=submitted">View all ↗</Link></div>
    {error && <p role="status" className={styles.recentCaption}>Could not refresh. Previously loaded records are retained.</p>}
    {jobs?.map(job => <article key={job.id}><span className={styles.recentAvatar}>{(job.company || "?").slice(0,2).toUpperCase()}</span><div><strong>{job.company || "Unknown company"}</strong><p>{job.title || "Unknown role"}</p><small>{job.submittedAt ? new Date(job.submittedAt).toLocaleString() : "Submission time not recorded"}</small></div><span className={styles.submittedBadge}>{statusView(job.status).label}</span></article>)}
    {!jobs && !error && <p className={styles.recentCaption}>Loading submissions…</p>}
    {jobs?.length === 0 && <p className={styles.recentCaption}>No submitted applications recorded yet.</p>}
  </section>;
}
