import type { AutopilotJobRow } from "./job-types";
import { INELIGIBILITY_LABELS, capCountdown } from "./job-presentation";
import styles from "./application-card.module.css";
import { LabApplicationCard } from "./lab-application-card";

export type CardProps = {
  detailed?: boolean; job: AutopilotJobRow; busy: string | null; onDetails: () => void; onApply: () => void;
  onAssistedFill?: () => void; onRetry?: () => void;
};

/** The Lab flip card; its actions live in the details popup it opens. */
export function ApplicationCard(props: CardProps) {
  return (
    <LabApplicationCard
      job={props.job}
      reason={cardReason(props.job)}
      detailed={props.detailed ?? false}
      onDetails={props.onDetails}
    />
  );
}

export function cardReason(job: AutopilotJobRow): string | null {
  return job.status === "INELIGIBLE"
    ? INELIGIBILITY_LABELS[String(job.ineligibilityReason)] || job.ineligibilityDetail || "Cannot be applied to"
    : job.status === "REJECTED"
      ? (job.rejectionEvidence?.subject ? `From: "${job.rejectionEvidence.subject}"` : "Marked rejected")
      : job.skipReason || job.lastError || null;
}

/** Apply / Autofill / Retry, shared by both card looks so they cannot drift. */
export function CardActions({ job, busy, onApply, onAssistedFill, onRetry }: Pick<CardProps, "job" | "busy" | "onApply" | "onAssistedFill" | "onRetry">) {
  const canApply = job.status === "QUEUED" || (job.status === "SKIPPED" && job.skipReason?.startsWith("Match score stayed below"));
  // Every bucket the user finishes by hand gets the same offer. Assisted fill
  // was restricted to MANUAL_REVIEW, so a Failed or Review application the user
  // intended to complete themselves had no way to get the form pre-filled and
  // they retyped it from scratch. These are exactly the buckets the state
  // selector already lets them relabel - the ones they are working through -
  // so the two should agree. QUEUED is excluded because the automation still
  // intends to try it, and SUBMITTED because it is already done.
  const ASSISTABLE = ["MANUAL_REVIEW", "FAILED", "NEEDS_REVIEW", "STAGED"];
  const canAssist = ASSISTABLE.includes(job.status || "");
  // A failed attempt is usually a bug we have since fixed, but without this the
  // card is a dead end: the only other action is claiming a submission that
  // never happened. Retry puts the job back in the queue and applies again.
  const canRetry = job.status === "FAILED";
  const paced = capCountdown(job);
  return (
    <>
      {canAssist && onAssistedFill && (
        <button
          type="button"
          className={styles.secondaryBtn}
          disabled={busy === job.id}
          onClick={(event) => { event.stopPropagation(); onAssistedFill(); }}
          title="Open this form in a browser with everything filled in — you solve the challenge and press Submit"
        >
          {busy === job.id ? "Filling…" : "Autofill & open"}
        </button>
      )}
      {canRetry && onRetry && (
        <button
          type="button"
          disabled={busy !== null}
          onClick={(event) => { event.stopPropagation(); onRetry(); }}
          title="Put this back in the queue and try applying again"
        >
          {busy === job.id ? "Retrying…" : "Retry →"}
        </button>
      )}
      {canApply && (
        <button
          type="button"
          disabled={busy !== null}
          onClick={(event) => { event.stopPropagation(); onApply(); }}
          title={
            paced
              ? "Send this now, ignoring the per-company limit"
              : "Start an Autopilot application for this role"
          }
        >
          {busy === job.id ? "Applying…" : paced ? "Apply anyway →" : "Apply →"}
        </button>
      )}
    </>
  );
}
