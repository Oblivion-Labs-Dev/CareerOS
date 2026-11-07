"use client";

import type { CSSProperties, ReactNode } from "react";
import { useSurfaceDepth } from "@/hooks/use-surface-depth";
import type { LabAccent } from "@/components/ui/lab-kpi-card";
import lab from "@/components/ui/lab-kpi-card.module.css";
import type { AutopilotJobRow } from "./job-types";
import { capCountdown, getJobReasonMeta, matchBand, relativeTime, statusView } from "./job-presentation";
import styles from "./lab-application-card.module.css";

/** One accent per status family; the status label always names it too. */
export function labAccentFor(statusKey: string): LabAccent {
  switch (statusKey) {
    case "submitted": return "green";
    case "review":
    case "manual":
    case "unverified": return "gold";
    case "failed": return "orange";
    case "skipped":
    case "ineligible":
    case "rejected": return "purple";
    default: return "blue";
  }
}

/** Friendly wording for each job state, written for people new to CareerOS. */
const PLAIN_STATUS: Record<string, { eyebrow: string; headline: string; detail?: string }> = {
  queued: { eyebrow: "Up next", headline: "Ready to send", detail: "Waiting in line. Apply sends it now." },
  applying: { eyebrow: "In progress", headline: "Sending your application now" },
  submitted: { eyebrow: "Sent", headline: "Application sent", detail: "Now it's up to the employer." },
  review: { eyebrow: "Check before sending", headline: "Ready for your review", detail: "Look it over, then send it." },
  manual: { eyebrow: "Needs you", headline: "Needs a quick look from you" },
  failed: { eyebrow: "Didn't go through", headline: "Couldn't finish sending" },
  unverified: { eyebrow: "Not sure it sent", headline: "It may have been sent", detail: "We couldn't confirm it. Check the employer's site." },
  skipped: { eyebrow: "Skipped", headline: "Skipped this one" },
  ineligible: { eyebrow: "Not a fit", headline: "You can't apply to this one" },
  rejected: { eyebrow: "Closed", headline: "Not moving forward" },
  discovered: { eyebrow: "New", headline: "Just found", detail: "Not checked against your profile yet." },
  scored: { eyebrow: "Checked", headline: "Checked against your profile" },
};

/** Plain-language versions of the reason categories in job-presentation. */
const PLAIN_REASONS: Record<string, { headline: string; detail: string }> = {
  captcha: { headline: "A robot check stopped us", detail: "The site wants proof you're human. Open it and finish the check yourself." },
  "cover-letter": { headline: "Needs a cover letter", detail: "This form won't send without one." },
  questions: { headline: "Needs your answers", detail: "The form asks questions only you can answer." },
  "manual-form": { headline: "Apply on their site", detail: "There's no online form we can fill in for this job." },
  expired: { headline: "This job has closed", detail: "The posting expired or was taken down." },
  citizenship: { headline: "U.S. citizens only", detail: "The role needs U.S. citizenship or a security clearance." },
  visa: { headline: "No visa sponsorship", detail: "The employer says they don't sponsor work visas." },
  location: { headline: "Based outside the U.S.", detail: "This role is located outside the United States." },
  duplicate: { headline: "Already applied", detail: "You've already sent an application for this job." },
  score: { headline: "Not a close enough match", detail: "The match score stayed below your minimum." },
  timeout: { headline: "The site was too slow", detail: "The page didn't load in time. Try again later." },
};

const listOf = (items: string[] | undefined, max: number) => {
  const clean = (items ?? []).map(item => item.trim()).filter(Boolean);
  if (!clean.length) return null;
  const extra = clean.length - max;
  return clean.slice(0, max).join(", ") + (extra > 0 ? ` +${extra}` : "");
};

/** Up to four short facts, each only when the job really has it. */
function backFacts(job: AutopilotJobRow, score: number | null) {
  const facts: { label: string; value: string }[] = [];
  if (score !== null) facts.push({ label: "Match", value: `${score}% · ${matchBand(score).label}` });
  const has = listOf(job.keyMatchingSkills, 3);
  if (has) facts.push({ label: "You have", value: has });
  const missing = listOf(job.missingSkills, 2);
  if (missing) facts.push({ label: "Missing", value: missing });
  const questions = job.pendingQuestions?.length ?? 0;
  if (questions > 0) facts.push({ label: "Questions", value: `${questions} waiting for you` });
  if (job.salary?.trim()) facts.push({ label: "Pay", value: job.salary.trim() });
  return facts.slice(0, 4);
}

/** The plain-language "where is this and what's next" for one job, from real fields only. */
export function labSummary(job: AutopilotJobRow, reason: string | null) {
  const status = statusView(job.status);
  const score = typeof job.matchScore === "number" && Number.isFinite(job.matchScore)
    ? Math.max(0, Math.min(100, Math.round(job.matchScore))) : null;
  const paced = capCountdown(job);
  const isPostProcessing = ["manual", "review", "failed", "ineligible", "skipped", "unverified"].includes(status.key);
  const reasonMeta = isPostProcessing ? getJobReasonMeta(job) : null;
  const plain = reasonMeta ? PLAIN_REASONS[reasonMeta.key] : undefined;
  const statusPlain = PLAIN_STATUS[status.key];
  return {
    eyebrow: paced ? "Paused for now" : statusPlain?.eyebrow ?? status.label,
    headline: plain?.headline ?? (paced ? "Waiting on your company limit" : statusPlain?.headline ?? reason ?? status.label),
    // A reason we have no friendly wording for is still real: show it as stored.
    detail: plain?.detail ?? (paced ? paced.detail : reason ?? statusPlain?.detail ?? null),
    facts: backFacts(job, score),
  };
}

/** Summary plus actions, shown at the top of the Lab details popup. */
export function LabJobSummary({ job, reason, actions }: { job: AutopilotJobRow; reason: string | null; actions?: ReactNode }) {
  const { eyebrow, headline, detail, facts } = labSummary(job, reason);
  return (
    <section className={styles.summary} data-accent={labAccentFor(statusView(job.status).key)} aria-label="Where this application stands">
      <span className={styles.eyebrow}>{eyebrow}</span>
      <strong className={styles.headline}>{headline}</strong>
      {detail ? <p className={styles.detail}>{detail}</p> : null}
      {facts.length ? (
        <dl className={styles.facts}>
          {facts.map(fact => (
            <div key={fact.label}>
              <dt>{fact.label}</dt>
              <dd title={fact.value}>{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </section>
  );
}

/**
 * Lab application card: one quiet matte face with identity, an editorial
 * title and the match score. It does nothing on hover beyond a slight lift;
 * a click (or Enter/Space) opens the details popup, which flips up out of
 * this card. Actions live in that popup so the grid stays calm.
 */
export function LabApplicationCard({ job, reason, detailed, onDetails }: {
  job: AutopilotJobRow;
  reason: string | null;
  detailed: boolean;
  onDetails: () => void;
}) {
  const surface = useSurfaceDepth(job.status);
  const status = statusView(job.status);
  const accent = labAccentFor(status.key);
  const score = typeof job.matchScore === "number" && Number.isFinite(job.matchScore)
    ? Math.max(0, Math.min(100, Math.round(job.matchScore))) : null;
  const initials = (job.company || "?").split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();
  const when = job.status === "SUBMITTED" && job.submittedAt
    ? `Submitted ${relativeTime(job.submittedAt)}`
    : job.updatedAt ? `Updated ${relativeTime(job.updatedAt)}` : null;
  // A paced job is queued and wanted, not stuck: the countdown stays on the
  // front so a held posting does not read as a stalled queue.
  const paced = capCountdown(job);

  return (
    <article
      ref={surface}
      className={`${lab.card} ${styles.card}`}
      title={reason || undefined}
      data-accent={accent}
      data-status={status.key}
      data-job-id={job.id}
      data-card-variant="lab"
      data-detailed={detailed || undefined}
      style={{ "--delay": "0ms" } as CSSProperties}
      role="button"
      tabIndex={0}
      aria-haspopup="dialog"
      aria-label={`Open details for ${job.title || "this role"} at ${job.company || "this company"}`}
      onClick={onDetails}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onDetails();
        }
      }}
    >
      <div className={styles.identity}>
        <span className={`${lab.icon} ${styles.monogram}`} aria-hidden="true">{initials}</span>
        <span className={styles.company}>{job.company || "Unknown company"}</span>
        <span className={styles.status}><i aria-hidden="true" />{status.label}</span>
      </div>
      <p className={styles.title}>{job.title || "Unknown role"}</p>
      <div className={styles.scoreRow}>
        <span className={lab.number} aria-label={score === null ? "Not scored" : `${score}% match`}>
          {score === null ? (
            <span className={lab.unknown}>—</span>
          ) : (
            <>
              {String(score).split("").map((ch, i) => (
                <span key={i} className={lab.digit} style={{ "--i": i } as CSSProperties}>{ch}</span>
              ))}
              <span className={styles.percent}>%</span>
            </>
          )}
        </span>
        <span className={styles.scoreLabel}>{score === null ? "Not scored" : "match"}</span>
        {score !== null ? (
          <span className={styles.meter} aria-hidden="true">
            <i style={{ transform: `scaleX(${score / 100})` }} />
          </span>
        ) : null}
      </div>
      <footer className={styles.footer}>
        <span>{job.location || "Location not listed"}</span>
        {paced ? (
          <span className={styles.paced} title={paced.detail}>{paced.label}</span>
        ) : when ? <span>{when}</span> : null}
      </footer>
    </article>
  );
}
