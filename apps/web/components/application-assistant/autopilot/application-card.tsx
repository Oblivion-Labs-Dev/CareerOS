import { identityTransition } from "@/lib/surface-transition";
import { useSurfaceDepth } from "@/hooks/use-surface-depth";
import type { AutopilotJobRow } from "./job-types";
import { useCountUp } from "./use-count-up";
import { INELIGIBILITY_LABELS, capCountdown, relativeTime, statusView } from "./job-presentation";
import styles from "./application-card.module.css";

export function ApplicationCard({ job, busy, onDetails, onApply, onAssistedFill, onRetry, detailed = false }: {
  detailed?: boolean; job: AutopilotJobRow; busy: string | null; onDetails: () => void; onApply: () => void;
  onAssistedFill?: () => void; onRetry?: () => void;
}) {
  const surface = useSurfaceDepth(job.status);
  const status = statusView(job.status);
  const score = typeof job.matchScore === "number" && Number.isFinite(job.matchScore)
    ? Math.max(0, Math.min(100, Math.round(job.matchScore))) : null;
  // Dial and number are driven by one animated value so they cannot disagree
  // mid-sweep: both climb from zero to the real score together.
  const shownScore = useCountUp(score);
  const canApply = job.status === "QUEUED" || (job.status === "SKIPPED" && job.skipReason?.startsWith("Match score stayed below"));
  const initials = (job.company || "?").split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();
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
  // Held by the per-employer rate limit. Recomputed from the stored expiry on
  // each render rather than trusted as a flag, so the badge clears itself when
  // the window rolls even if the row has not been rewritten yet.
  const paced = capCountdown(job);
  const reason = job.status === "INELIGIBLE"
    ? INELIGIBILITY_LABELS[String(job.ineligibilityReason)] || job.ineligibilityDetail || "Cannot be applied to"
    : job.status === "REJECTED"
      ? (job.rejectionEvidence?.subject ? `From: "${job.rejectionEvidence.subject}"` : "Marked rejected")
      : job.skipReason || job.lastError || null;
  return (
    // The whole card opens the dossier — there is no separate View button to
    // aim for. Inner controls stop propagation so Apply and Autofill still do
    // their own thing. Changing which bucket a job sits in lives in the side
    // panel, not here.
    <article
      ref={surface}
      className={`${styles.card} appCard`}
      title={reason || undefined}
      data-status={status.key}
      data-job-id={job.id}
      role="button"
      tabIndex={0}
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
        <span className={styles.monogram} style={{viewTransitionName: detailed ? "none" : identityTransition(job.id)}} aria-hidden="true">{initials}</span>
        <div className={styles.company}>{job.company || "Unknown company"}</div>
        <span className={styles.status}><i />{status.label}</span>
      </div>
      {paced && (
        // A paced job is queued and wanted, not stuck — so this is a countdown
        // next to the status rather than a second status. Apply still works and
        // overrides the limit, which the tooltip says so the button does not
        // look like it will be refused.
        <p className={styles.paced} title={paced.detail}>
          <span aria-hidden="true">⏳</span>
          <span>{paced.label}</span>
        </p>
      )}
      <p className={styles.title}>{job.title || "Unknown role"}</p>
      <p className={styles.location}>{job.location || "Location not listed"}</p>
      {score !== null && (
        <div className={styles.dossier}>
          <div className={styles.fit}>
            <span className={styles.matchScore} aria-label={`${score}% match`}>{shownScore ?? score}%</span>
          </div>
        </div>
      )}
      {reason && <p className={styles.reason}>{reason}</p>}
      <footer className={styles.footer}>
        <span>{job.status === "SUBMITTED" && job.submittedAt ? `Submitted ${relativeTime(job.submittedAt)}` : job.updatedAt ? `Updated ${relativeTime(job.updatedAt)}` : "Application workspace"}</span>
        <span className={styles.actions}>
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
        </span>
      </footer>
    </article>
  );
}
