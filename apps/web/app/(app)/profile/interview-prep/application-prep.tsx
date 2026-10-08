"use client";

import { useEffect, useState } from "react";
import { InterviewChecklistView, type ChecklistSection } from "./checklist-view";
import styles from "./checklist.module.css";

type Prep = {
  resumeId: string; label: string; company: string; title: string; jobUrl: string; jdText: string; pdfSha256: string | null;
  application: { channel?: string; autopilot_job_id?: string; submitted_at?: string; linked_at?: string } | null;
  sections: ChecklistSection[];
};

/** Prep for one application, built from the exact resume version submitted and the JD it was written against. */
export function ApplicationPrep({ resumeId }: { resumeId: string }) {
  const [prep, setPrep] = useState<Prep | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`/api/backend/career/resumes/${resumeId}/interview-prep`, { credentials: "include" })
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not load this application.");
        setPrep(data as Prep);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load this application."));
  }, [resumeId]);

  if (error) return <div className={styles.page}><p role="alert">{error}</p></div>;
  if (!prep) return <div className={styles.page}><p role="status">Loading interview prep…</p></div>;
  const app = prep.application;
  const when = (app?.submitted_at ?? app?.linked_at ?? "").slice(0, 10);
  const how = app ? (app.channel === "manual" ? "applied manually" : "applied with Autopilot") : "not applied yet";
  return <InterviewChecklistView checklist={{
    title: `Interview prep · ${[prep.title, prep.company].filter(Boolean).join(" at ") || prep.label}`,
    basis: `Built from the exact resume you submitted (${prep.label}${prep.pdfSha256 ? `, PDF ${prep.pdfSha256.slice(0, 10)}` : ""}), ${how}${when ? ` on ${when}` : ""}, and the job description it was written against. No AI calls: every item comes from your career record.`,
    sections: prep.sections,
  }}>
    <div className={styles.links}>
      <a href={`/api/backend/career/resumes/${prep.resumeId}/download?format=pdf`}>Submitted resume (PDF)</a>
      {prep.jobUrl ? <a href={prep.jobUrl} target="_blank" rel="noopener noreferrer">Original posting ↗</a> : null}
    </div>
    {prep.jdText ? <details className={styles.jd}><summary>Original job description</summary><pre>{prep.jdText}</pre></details> : null}
  </InterviewChecklistView>;
}
