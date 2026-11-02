import { WorkspaceLoading } from "@/components/ui/workspace-loading";
import { useEffect, useState } from "react";
import styles from "./application-journey.module.css";

type Journey = {
  assessment: { state: string; label: string; explanation: string };
  events: { title: string; at?: string; detail: string; source: string }[];
  receipt: { receiptId: string; submittedAt?: string; confirmationText?: string; resumeFileUsed?: string; tailoringMode?: string; fieldVerificationStatus?: string; fieldsCount?: number } | null;
  evidence: { kind: string; label: string; url: string }[];
  linkedPipeline: string | null; linkedEmail: boolean; nextAction: string;
};

export function ApplicationJourney({ jobId, view = "Journey" }: { jobId: string; view?: "Overview" | "Journey" | "Documents" }) {
  const [data, setData] = useState<Journey | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(false);
    fetch(`/api/backend/application-assistant/jobs/${encodeURIComponent(jobId)}/journey`, { signal: controller.signal, cache: "no-store" })
      .then(async response => { if (!response.ok) throw new Error("Unavailable"); return response.json() as Promise<Journey>; })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [jobId, revision]);
  if (error) return <section className={styles.journey}><p role="alert">Could not load this application's evidence.</p><button onClick={() => setRevision(n => n + 1)}>Retry</button></section>;
  if (!data) return <WorkspaceLoading label="Loading application journey…" shape="list" rows={4} />;
  return <section className={styles.journey} aria-label="Connected application journey">
    <div className={styles.assessment} data-state={data.assessment.state}><span>SUBMISSION EVIDENCE</span><h3>{data.assessment.label}</h3><p>{data.assessment.explanation}</p></div>
    <div hidden={view !== "Documents"}>
    {data.receipt?.resumeFileUsed && <div className={styles.resumeStack}><span aria-hidden="true">▤</span><div><small>ARCHIVED SUBMISSION VERSION</small><strong>{data.receipt.resumeFileUsed}</strong><p>{data.receipt.tailoringMode || "Tailoring mode not recorded"}</p></div></div>}
    {data.receipt && <details className={styles.receipt} open><summary>Submission receipt <span>↗</span></summary><dl><div><dt>Receipt</dt><dd>{data.receipt.receiptId}</dd></div><div><dt>Archived</dt><dd>{data.receipt.submittedAt ? new Date(data.receipt.submittedAt).toLocaleString() : "Not recorded"}</dd></div><div><dt>Resume version</dt><dd>{data.receipt.resumeFileUsed || "Not recorded"}</dd></div><div><dt>Tailoring mode</dt><dd>{data.receipt.tailoringMode || "Not recorded"}</dd></div><div><dt>Field verification</dt><dd>{data.receipt.fieldVerificationStatus || "Not recorded"}</dd></div></dl>{data.receipt.confirmationText && <blockquote>{data.receipt.confirmationText}</blockquote>}<p className={styles.caption}>Archived text and verification labels are shown as recorded, including legacy values.</p></details>}
    {data.evidence.length > 0 && <div className={styles.evidence}>{data.evidence.map(item => <a key={item.kind} href={item.url} target="_blank" rel="noopener noreferrer"><span aria-hidden="true">▧</span><strong>{item.label}</strong><small>Open saved screenshot ↗</small></a>)}</div>}
    </div>
    <div hidden={view !== "Journey"}>
    <h3 className={styles.heading}>One application. The whole story.</h3>
    <ol className={styles.timeline}>{data.events.map((event,index) => <li key={`${event.at}-${index}`}><span className={styles.dot} /><div><small>{event.source}{event.at ? ` · ${new Date(event.at).toLocaleString()}` : " · Time not recorded"}</small><strong>{event.title.replaceAll("_", " ")}</strong>{event.detail && <p>{event.detail}</p>}</div></li>)}</ol>
    {!data.events.length && <p className={styles.caption}>No dated activity has been recorded yet.</p>}
    <div className={styles.connections}><div><span>Pipeline</span><strong>{data.linkedPipeline || "No linked record"}</strong></div><div><span>Email</span><strong>{data.linkedEmail ? "Tracking-address message recorded" : "No linked message"}</strong></div></div>
    </div>
    <div className={styles.next}><span>NEXT STEP</span><p>{data.nextAction}</p></div>
  </section>;
}
