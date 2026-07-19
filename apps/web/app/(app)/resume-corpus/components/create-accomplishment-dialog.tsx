"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { NewAccomplishmentInput } from "../corpus-model";
import styles from "../resume-corpus.module.css";

interface CreateAccomplishmentDialogProps {
  open: boolean;
  onClose: () => void;
  onCreate: (input: NewAccomplishmentInput) => Promise<void>;
}

const EMPTY_INPUT: NewAccomplishmentInput = {
  title: "",
  company: "",
  role: "",
  timePeriod: "",
  summary: "",
  metricName: "",
  metricValue: "",
  technologies: [],
};

export function CreateAccomplishmentDialog({ open, onClose, onCreate }: CreateAccomplishmentDialogProps) {
  const [input, setInput] = useState<NewAccomplishmentInput>(EMPTY_INPUT);
  const [technologies, setTechnologies] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setInput(EMPTY_INPUT);
    setTechnologies("");
    setError(null);
    window.requestAnimationFrame(() => titleRef.current?.focus());
    return () => previousFocusRef.current?.focus();
  }, [open]);

  if (!open) return null;

  const setField = <Key extends keyof NewAccomplishmentInput>(key: Key, value: NewAccomplishmentInput[Key]) => {
    setInput((current) => ({ ...current, [key]: value }));
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!input.title.trim() || !input.summary.trim()) {
      setError("Add a short title and enough context to make the story recognizable.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        ...input,
        technologies: technologies.split(",").map((item) => item.trim()).filter(Boolean),
      });
      onClose();
    } catch {
      setError("The accomplishment could not be saved. Your draft is still here—try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const trapFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled])') ?? []);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className={styles.overlay} onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={dialogRef} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="create-accomplishment-title" onKeyDown={trapFocus}>
        <div className={styles.dialogHeader}>
          <div>
            <h2 id="create-accomplishment-title">Record an accomplishment</h2>
            <p>Start with what you know. The workspace will surface the missing proof, decisions, and interview questions next.</p>
          </div>
          <button type="button" className={styles.iconButton} onClick={onClose} aria-label="Close">×</button>
        </div>
        <form onSubmit={submit}>
          <div className={styles.dialogBody}>
            {error ? <div className={styles.saveBanner} role="alert">{error}</div> : null}
            <div className={styles.fieldGrid}>
              <div className={styles.fieldGroupFull}>
                <label className={styles.label} htmlFor="create-title">Short story title</label>
                <input ref={titleRef} id="create-title" className={styles.field} value={input.title} onChange={(event) => setField("title", event.currentTarget.value)} placeholder="e.g. Regional event-routing platform" />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.label} htmlFor="create-company">Company or organization</label>
                <input id="create-company" className={styles.field} value={input.company} onChange={(event) => setField("company", event.currentTarget.value)} />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.label} htmlFor="create-role">Your role</label>
                <input id="create-role" className={styles.field} value={input.role} onChange={(event) => setField("role", event.currentTarget.value)} />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.label} htmlFor="create-period">Time period</label>
                <input id="create-period" className={styles.field} value={input.timePeriod} onChange={(event) => setField("timePeriod", event.currentTarget.value)} placeholder="2024 — 2026" />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.label} htmlFor="create-technologies">Skills or technologies</label>
                <input id="create-technologies" className={styles.field} value={technologies} onChange={(event) => setTechnologies(event.currentTarget.value)} placeholder="Comma separated" />
              </div>
              <div className={styles.fieldGroupFull}>
                <label className={styles.label} htmlFor="create-summary">What changed because of your work?</label>
                <textarea id="create-summary" className={styles.textarea} rows={5} value={input.summary} onChange={(event) => setField("summary", event.currentTarget.value)} placeholder="Describe the problem, your contribution, and the outcome in plain language." />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.label} htmlFor="create-metric-name">Metric name (optional)</label>
                <input id="create-metric-name" className={styles.field} value={input.metricName} onChange={(event) => setField("metricName", event.currentTarget.value)} placeholder="Availability, cost, adoption..." />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.label} htmlFor="create-metric-value">Metric value (optional)</label>
                <input id="create-metric-value" className={styles.field} value={input.metricValue} onChange={(event) => setField("metricValue", event.currentTarget.value)} placeholder="99.99%, −34%, 70 teams..." />
              </div>
            </div>
          </div>
          <div className={styles.dialogFooter}>
            <button type="button" className={styles.quietButton} onClick={onClose}>Cancel</button>
            <button type="submit" className={styles.primaryButton} disabled={submitting}>{submitting ? "Saving..." : "Create and open"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
