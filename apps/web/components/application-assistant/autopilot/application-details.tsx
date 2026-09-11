import { identityTransition } from "@/lib/surface-transition";
import { useEffect, useState } from "react";
import { ApplicationJourney } from "./application-journey";
import type { AutopilotJobRow } from "./job-types";
import { INELIGIBILITY_LABELS, matchBand, statusView } from "./job-presentation";
import { getAutopilotJobStates, type AutopilotJobState } from "@/lib/application-assistant-api";
import styles from "./application-details.module.css";

/** Copy text, falling back to a selection-based copy where the clipboard API
 *  is unavailable (it needs a secure context, which a plain-HTTP dev host is
 *  not). Returns whether it worked, so the caller only shows a tick on success.
 */
async function copyText(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Fall through to the legacy path rather than failing silently.
  }
  try {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}

function date(value?: string) {
  if (!value || !Number.isFinite(Date.parse(value))) return "Not recorded";
  return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function ApplicationDetails({
  job,
  onClose,
  answerDrafts,
  onDraftChange,
  onApprove,
  onSkip,
  onSetState,
  busy,
}: {
  job: AutopilotJobRow;
  onClose: () => void;
  /** Draft answers keyed `${job.id}:${question}` — shared with the card grid. */
  answerDrafts?: Record<string, string>;
  onDraftChange?: (question: string, value: string) => void;
  onApprove?: () => void;
  onSkip?: () => void;
  /** Record what actually happened with this application. */
  onSetState?: (status: string, label: string) => void;
  busy?: boolean;
}) {
  const [tab, setTab] = useState<"Overview" | "Journey" | "Documents">("Overview");
  // The allowed states and which buckets may be relabelled are the backend's
  // decision, so the panel asks rather than hardcoding a second copy that can
  // drift out of step with what the API will actually accept.
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [states, setStates] = useState<AutopilotJobState[]>([]);
  const [settableFrom, setSettableFrom] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    getAutopilotJobStates()
      .then((res) => {
        if (!live) return;
        setStates(res.states || []);
        setSettableFrom(res.settableFrom || []);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  const canSetState = settableFrom.includes(job.status || "");
  const status = statusView(job.status);
  const score = typeof job.matchScore === "number" && Number.isFinite(job.matchScore) ? Math.min(100, Math.max(0, Math.round(job.matchScore))) : null;
  const reason = job.status === "INELIGIBLE" ? job.ineligibilityDetail || INELIGIBILITY_LABELS[job.ineligibilityReason || ""] || job.lastError : job.skipReason || job.lastError;
  const answers = Object.entries(job.answers || {});
  // Autopilot stops on a question it cannot answer from the profile. The panel
  // is where the user is already looking at that application, so the question
  // belongs here rather than only in a separate list.
  const copyJobId = async (id: string) => {
    if (await copyText(id)) {
      setCopiedId(id);
      window.setTimeout(() => setCopiedId((current) => (current === id ? null : current)), 1600);
    }
  };

  const awaitingAnswer = job.status === "NEEDS_REVIEW" || job.status === "STAGED";
  const pendingQuestions = awaitingAnswer ? job.pendingQuestions || [] : [];
  return <div className={styles.detail} data-status={status.key}>
    <header className={styles.hero}>
      <div className={styles.topline}><span>APPLICATION DOSSIER</span><button type="button" aria-label="Close" onClick={onClose}>×</button></div>
      <div className={styles.identity}><span className={styles.monogram} style={{viewTransitionName: identityTransition(job.id)}} aria-hidden="true">{(job.company || "?").slice(0,2).toUpperCase()}</span><div><span className={styles.badge}><i />{status.label}</span><h2 id="application-details-title">{job.company || "Unknown company"}</h2></div></div>
      <h3>{job.title || "Unknown role"}</h3><p className={styles.location}>⌖ {job.location || "Location not listed"}</p>
      {job.applicationUrl && (
        <a
          className={styles.heroPosting}
          href={job.applicationUrl}
          target="_blank"
          rel="noopener noreferrer"
          title={job.applicationUrl}
        >
          <span aria-hidden="true">⧉</span>
          <span>Open original job posting</span>
          <b aria-hidden="true">↗</b>
        </a>
      )}
      {/* The job id, click to copy. It is the only handle that identifies this
          application in the database and the logs, so when a status looks wrong
          it is the first thing needed to investigate — and retyping a UUID from
          a screenshot is exactly the friction that stops a problem being
          reported at all. */}
      <button
        type="button"
        className={styles.heroJobId}
        data-copied={copiedId === job.id ? "true" : undefined}
        onClick={() => copyJobId(job.id)}
        title="Click to copy"
        aria-label={`Copy job ID ${job.id}`}
      >
        <span aria-hidden="true">#</span>
        <code>{job.id}</code>
        {/* Announced politely so a screen reader hears the confirmation without
            the whole control being re-read. */}
        <em aria-live="polite">{copiedId === job.id ? "Copied to clipboard" : ""}</em>
      </button>
      <div className={styles.heroArt} aria-hidden="true"><i /><i /><span>↗</span></div>
    </header>
    {canSetState && onSetState && states.length > 0 && (
      <div className={styles.stateBar} data-status={status.key}>
        <label htmlFor="application-state-picker">What happened with this one?</label>
        <select
          id="application-state-picker"
          className={styles.statePicker}
          aria-label="Set application state"
          value=""
          disabled={busy}
          onChange={(event) => {
            const picked = states.find((state) => state.value === event.target.value);
            if (picked) onSetState(picked.value, picked.label);
            event.target.value = "";
          }}
        >
          <option value="" disabled>{busy ? "Saving…" : "Choose a state…"}</option>
          {states.map((state) => (
            <option key={state.value} value={state.value} data-state={statusView(state.value).key}>
              {state.label}
            </option>
          ))}
        </select>
      </div>
    )}
    <nav className={styles.detailTabs} data-status={status.key} aria-label="Application detail sections">{(["Overview", "Journey", "Documents"] as const).map(name => <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}</button>)}</nav>
    <div className={styles.body}>
      <ApplicationJourney jobId={job.id} view={tab} />
      <div hidden={tab !== "Overview"}>
      <section className={styles.fit} aria-label="Application summary">
        <div className={styles.dial}><svg viewBox="0 0 80 80" aria-hidden="true"><circle cx="40" cy="40" r="34" /><circle cx="40" cy="40" r="34" pathLength="100" strokeDasharray={`${score || 0} 100`} /></svg><strong>{score ?? "—"}<small>{score === null ? "" : "%"}</small></strong></div>
        <div><span className={styles.eyebrow}>PROFILE MATCH</span><h3>{score === null ? "Not scored yet" : matchBand(score).label}</h3><p>{job.matchMethod === "heuristic" ? "Keyword comparison" : job.matchModel ? `Scored with ${job.matchModel}` : "Recorded application match"}</p></div>
      </section>
      <div className={styles.facts}><div><span>LAST UPDATED</span><strong>{date(job.updatedAt)}</strong></div><div><span>{job.status === "SUBMITTED" ? "SUBMITTED" : "ADDED TO QUEUE"}</span><strong>{date(job.status === "SUBMITTED" ? job.submittedAt : job.queuedAt)}</strong></div></div>
      {reason && <section className={styles.reason}><span className={styles.eyebrow}>{job.status === "SUBMITTED" ? "RECORDED NOTE" : "WHY IT STOPPED"}</span><p>{reason}</p>{job.lastErrorType && <small>{job.lastErrorType}</small>}</section>}
      {awaitingAnswer && (
        <section className={styles.section} aria-label="Questions waiting on you">
          <div className={styles.sectionTitle}>
            <span aria-hidden="true">✎</span>
            <h3>Waiting on you</h3>
            {pendingQuestions.length > 0 && <b>{pendingQuestions.length}</b>}
          </div>
          {pendingQuestions.length === 0 ? (
            <p className={styles.prose}>{job.lastError || "Autopilot stopped and did not record a specific question."}</p>
          ) : (
            pendingQuestions.map((question) => {
              const draftKey = `${job.id}:${question.question}`;
              const value = answerDrafts?.[draftKey] ?? "";
              return (
                <div key={question.question} className={styles.pendingQuestion}>
                  <p className={styles.eyebrow}>QUESTION</p>
                  <p className={styles.prose}>{question.question}</p>
                  {question.options && question.options.length > 0 ? (
                    <select
                      className={styles.answerInput}
                      aria-label={question.question}
                      value={value}
                      onChange={(event) => onDraftChange?.(question.question, event.target.value)}
                    >
                      <option value="">Select an answer…</option>
                      {question.options.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      className={styles.answerInput}
                      aria-label={question.question}
                      placeholder="Your answer…"
                      value={value}
                      onChange={(event) => onDraftChange?.(question.question, event.target.value)}
                    />
                  )}
                </div>
              );
            })
          )}
          {(onApprove || onSkip) && (
            <div className={styles.pendingActions}>
              {onApprove && (
                <button type="button" className={styles.primaryAction} disabled={busy} onClick={onApprove}>
                  {busy ? "Applying…" : "Approve & continue"}
                </button>
              )}
              {onSkip && (
                <button type="button" className={styles.secondaryAction} disabled={busy} onClick={onSkip}>
                  Skip application
                </button>
              )}
            </div>
          )}
        </section>
      )}
      {(job.matchReason || job.keyMatchingSkills?.length || job.missingSkills?.length) ? <section className={styles.section}><div className={styles.sectionTitle}><span aria-hidden="true">◎</span><h3>How your experience fits</h3></div>{job.matchReason && <p className={styles.prose}>{job.matchReason}</p>}{Boolean(job.keyMatchingSkills?.length) && <><p className={styles.eyebrow}>MATCHING SKILLS</p><div className={styles.skills}>{job.keyMatchingSkills?.map(skill => <span key={skill}>✓ {skill}</span>)}</div></>}{Boolean(job.missingSkills?.length) && <><p className={styles.eyebrow}>SKILL GAPS</p><div className={`${styles.skills} ${styles.gaps}`}>{job.missingSkills?.map(skill => <span key={skill}>{skill}</span>)}</div></>}</section> : null}
      {answers.length > 0 && <section className={styles.section}><div className={styles.sectionTitle}><span aria-hidden="true">≋</span><h3>Recorded answers</h3><b>{answers.length}</b></div><dl className={styles.answers}>{answers.map(([key,value]) => <div key={key} className={styles.answerRow}><dt>{key}</dt><dd>{typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "—")}</dd></div>)}</dl></section>}

      </div>
      <div hidden={tab !== "Documents"}>
      <section className={styles.section}><div className={styles.sectionTitle}><span aria-hidden="true">▤</span><h3>Application documents</h3></div>
        {job.resumeFileUsed ? <a className={styles.document} href={`/api/backend/application-assistant/autopilot/jobs/${job.id}/resume`} target="_blank" rel="noopener noreferrer"><span className={styles.paper} aria-hidden="true">▤</span><span><strong>Resume used</strong><small>{job.resumeFileUsed}</small></span><b aria-hidden="true">↗</b></a> : <p className={styles.muted}>No resume file recorded for this application.</p>}
      </section>
      </div>
    </div>
  </div>;
}
