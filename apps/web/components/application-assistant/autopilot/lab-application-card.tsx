"use client";

import { useState, type CSSProperties, type ReactNode } from "react";
import { identityTransition } from "@/lib/surface-transition";
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

const finePointer = () =>
  typeof window !== "undefined" && !!window.matchMedia && window.matchMedia("(hover: hover) and (pointer: fine)").matches;

/**
 * Lab flip version of the application card. The front carries identity and
 * the match score as clay digits; the back carries why the job is where it is
 * and what you can do about it. With a mouse the card turns on hover and a
 * click still opens the dossier, so nothing is a step further away than in
 * Classic. On touch, the first tap turns it and the back holds "Details".
 * Kept deliberately quiet: an editorial title, a light-weight score with one
 * thin match bar, and a single filled primary action on the back. The back is
 * written in plain words and lists only facts the job really has.
 */
export function LabApplicationCard({ job, reason, actions, detailed, onDetails }: {
  job: AutopilotJobRow;
  reason: string | null;
  actions: ReactNode;
  detailed: boolean;
  onDetails: () => void;
}) {
  const surface = useSurfaceDepth(job.status);
  const [flipped, setFlipped] = useState(false);
  const status = statusView(job.status);
  const accent = labAccentFor(status.key);
  const score = typeof job.matchScore === "number" && Number.isFinite(job.matchScore)
    ? Math.max(0, Math.min(100, Math.round(job.matchScore))) : null;
  const paced = capCountdown(job);
  const isPostProcessing = ["manual", "review", "failed", "ineligible", "skipped", "unverified"].includes(status.key);
  const reasonMeta = isPostProcessing ? getJobReasonMeta(job) : null;
  const initials = (job.company || "?").split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();
  const when = job.status === "SUBMITTED" && job.submittedAt
    ? `Submitted ${relativeTime(job.submittedAt)}`
    : job.updatedAt ? `Updated ${relativeTime(job.updatedAt)}` : null;

  // The back answers "where is this and what's next?" in plain words, from
  // real fields only. Anything the job doesn't have is simply left out.
  const plain = reasonMeta ? PLAIN_REASONS[reasonMeta.key] : undefined;
  const statusPlain = PLAIN_STATUS[status.key];
  const eyebrow = paced ? "Paused for now" : statusPlain?.eyebrow ?? status.label;
  const headline = plain?.headline ?? (paced ? "Waiting on your company limit" : statusPlain?.headline ?? reason ?? status.label);
  // A reason we have no friendly wording for is still real: show it as stored.
  const detail = plain?.detail ?? (paced ? paced.detail : reason ?? statusPlain?.detail ?? null);
  const facts = backFacts(job, score);

  return (
    <article
      ref={surface}
      className={`${lab.card} ${styles.card}`}
      title={reason || undefined}
      data-accent={accent}
      data-flipped={flipped}
      data-status={status.key}
      data-job-id={job.id}
      data-card-variant="lab"
      style={{ "--delay": "0ms" } as CSSProperties}
      role="button"
      tabIndex={0}
      aria-pressed={flipped}
      aria-label={`Open details for ${job.title || "this role"} at ${job.company || "this company"}`}
      onClick={(event) => {
        if ((event.target as HTMLElement).closest("button")) return;
        if (finePointer()) onDetails();
        else setFlipped(f => !f);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") { setFlipped(false); return; }
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onDetails();
        }
      }}
      onMouseLeave={() => setFlipped(false)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFlipped(false);
      }}
    >
      <div className={`${lab.face} ${lab.front} ${styles.front}`}>
        <div className={styles.identity}>
          <span
            className={`${lab.icon} ${styles.monogram}`}
            style={{ viewTransitionName: detailed ? "none" : identityTransition(job.id) }}
            aria-hidden="true"
          >
            {initials}
          </span>
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
          {when ? <span>{when}</span> : null}
        </footer>
      </div>
      <div className={`${lab.face} ${lab.back} ${styles.back}`}>
        <span className={lab.eyebrow}>{eyebrow}</span>
        <strong className={styles.headline}>{headline}</strong>
        {detail ? <small className={styles.detail}>{detail}</small> : null}
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
        <span className={styles.actions}>
          {actions}
          <button
            type="button"
            className={styles.detailsBtn}
            onClick={(event) => { event.stopPropagation(); onDetails(); }}
          >
            Details →
          </button>
        </span>
      </div>
    </article>
  );
}
