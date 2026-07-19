"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { CorpusRecord } from "../corpus-model";
import { gapCategoryField, generateMissingQuestions, getFocusQueue, type GapCategoryId, type GapItem } from "../corpus-quality";
import { QualityStatusBadge } from "./corpus-quality-ui";
import styles from "../resume-corpus.module.css";

interface CorpusFocusModeProps {
  open: boolean;
  record: CorpusRecord;
  onClose: () => void;
  onSaveAnswer: (questionId: string, answer: string) => void;
  onSaveField?: (field: keyof CorpusRecord, value: string) => void;
  onSkip?: () => void;
  onMarkNotApplicable?: (gapId: string) => void;
  onAttachEvidence?: (gapId: GapCategoryId, evidence: { name: string; type: string; url: string }) => void;
}

function pushResearchTask(record: CorpusRecord, gap: GapItem, notes: string) {
  try {
    const key = "careeros:corpus:research-tasks";
    const existing = JSON.parse(window.localStorage.getItem(key) ?? "[]") as Array<Record<string, string>>;
    const next = [
      {
        id: `${record.id}-${gap.id}-${Date.now()}`,
        recordId: record.id,
        recordTitle: record.title,
        missingFact: gap.missingDetail || gap.question,
        whyItMatters: gap.whyItMatters,
        whereToLook: "Project docs, dashboards, launch reviews, or performance feedback",
        suggestedSource: "Focus mode task",
        priority: gap.resumeImpact,
        notes: notes.trim(),
        status: "open",
        createdAt: new Date().toISOString(),
      },
      ...existing,
    ].slice(0, 40);
    window.localStorage.setItem(key, JSON.stringify(next));
    window.dispatchEvent(new Event("careeros:corpus:research-updated"));
  } catch {
    // Focus mode still works if storage is unavailable.
  }
}

function markGapNotApplicable(recordId: string, gapId: string) {
  try {
    const key = `careeros:corpus:na-gaps:${recordId}`;
    const existing = JSON.parse(window.localStorage.getItem(key) ?? "[]") as string[];
    if (!existing.includes(gapId)) {
      window.localStorage.setItem(key, JSON.stringify([...existing, gapId]));
    }
  } catch {
    // Skip still advances the queue.
  }
}

export function CorpusFocusMode({
  open,
  record,
  onClose,
  onSaveAnswer,
  onSaveField,
  onSkip,
  onMarkNotApplicable,
  onAttachEvidence,
}: CorpusFocusModeProps) {
  const queue = useMemo(() => getFocusQueue(record), [record]);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [notes, setNotes] = useState("");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [showFollowUps, setShowFollowUps] = useState(false);
  const [evidenceDraft, setEvidenceDraft] = useState({ name: "", type: "doc", url: "" });
  const dialogRef = useRef<HTMLDivElement>(null);
  const answerRef = useRef<HTMLTextAreaElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const current = queue[index];
  const gap: GapItem | undefined = current && "type" in current && current.type === "question" ? current.gap : (current as GapItem | undefined);
  const question = current && "type" in current && current.type === "question" ? current.question : undefined;
  const followUps = useMemo(() => generateMissingQuestions(record).filter((item) => item.category === gap?.id).slice(0, 4), [record, gap?.id]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setIndex(0);
    setAnswer(question?.preparedAnswer ?? "");
    setNotes("");
    setStatusMessage(null);
    setShowFollowUps(false);
    setEvidenceDraft({ name: "", type: "doc", url: "" });
    const frame = window.requestAnimationFrame(() => answerRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      previousFocusRef.current?.focus();
    };
  }, [open, record.id]);

  useEffect(() => {
    if (question) setAnswer(question.preparedAnswer ?? "");
    else setAnswer("");
  }, [index, question]);

  if (!open || !current || !gap) return null;

  const handleDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ) ?? []);
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

  const advance = () => {
    if (index < queue.length - 1) setIndex((value) => value + 1);
    else onClose();
  };

  const handleSave = () => {
    if (question && answer.trim()) {
      onSaveAnswer(question.id, answer.trim());
    } else if (answer.trim()) {
      const field = gapCategoryField(gap.id);
      if (field) onSaveField?.(field, answer.trim());
    }
    advance();
  };

  const handleSaveDraft = () => {
    if (question && answer.trim()) onSaveAnswer(question.id, answer.trim());
    else if (answer.trim()) {
      const field = gapCategoryField(gap.id);
      if (field) onSaveField?.(field, answer.trim());
    }
    setStatusMessage("Draft saved. Stay here or move to the next item.");
  };

  return (
    <div ref={dialogRef} className={styles.focusOverlay} role="dialog" aria-modal="true" aria-label="Focus mode" onKeyDown={handleDialogKeyDown}>
      <div className={styles.focusPanel}>
        <header className={styles.focusHeader}>
          <div>
            <span className={styles.eyebrow}>Focus mode</span>
            <h2>{record.title}</h2>
            <p>{record.company} · {index + 1} of {queue.length}</p>
          </div>
          <button type="button" className={styles.iconButton} onClick={onClose} aria-label="Exit focus mode">×</button>
        </header>

        <div className={styles.focusBullet}>
          <span className={styles.label}>Current bullet</span>
          <p>{record.currentBullet || record.summary}</p>
        </div>

        <div className={styles.focusGap}>
          <div className={styles.focusGapTop}>
            <QualityStatusBadge status={gap.status} />
            <span className={styles.focusGapCategory}>{gap.category}</span>
          </div>
          <p className={styles.focusWhy}><strong>Why it matters:</strong> {gap.whyItMatters}</p>
          <p className={styles.focusQuestion}>{question?.question ?? gap.question}</p>
        </div>

        <div className={styles.fieldGroup}>
          <label className={styles.label} htmlFor="focus-answer">Your answer</label>
          <textarea
            ref={answerRef}
            id="focus-answer"
            className={styles.textarea}
            rows={8}
            value={answer}
            onChange={(event) => setAnswer(event.currentTarget.value)}
            placeholder="Be specific: decision, tradeoff, metric, and your ownership."
          />
        </div>

        {record.evidence[0] ? (
          <div className={styles.intelBlock}>
            <span>Relevant evidence</span>
            <p>{record.evidence[0].name} ({record.evidence[0].type})</p>
          </div>
        ) : null}

        {onAttachEvidence ? (
          <div className={styles.focusEvidenceComposer}>
            <strong>Attach evidence to this item</strong>
            <input className={styles.field} aria-label="Focus evidence name" placeholder="Artifact name" value={evidenceDraft.name} onChange={(event) => setEvidenceDraft((current) => ({ ...current, name: event.currentTarget.value }))} />
            <input className={styles.field} aria-label="Focus evidence URL or path" placeholder="URL or safe path" value={evidenceDraft.url} onChange={(event) => setEvidenceDraft((current) => ({ ...current, url: event.currentTarget.value }))} />
            <select className={styles.select} aria-label="Focus evidence type" value={evidenceDraft.type} onChange={(event) => setEvidenceDraft((current) => ({ ...current, type: event.currentTarget.value }))}><option value="doc">Document</option><option value="rfc">RFC</option><option value="dashboard">Dashboard</option><option value="pr">Pull request</option><option value="screenshot">Screenshot</option></select>
            <button type="button" className={styles.quietButton} disabled={!evidenceDraft.name.trim() || !evidenceDraft.url.trim()} onClick={() => { onAttachEvidence(gap.id, evidenceDraft); setEvidenceDraft({ name: "", type: "doc", url: "" }); setStatusMessage("Evidence attached to this gap."); }}>Attach evidence</button>
          </div>
        ) : null}

        {showFollowUps ? (
          <div className={styles.answerBlock} aria-live="polite">
            <strong>Likely follow-up prompts</strong>
            {followUps.length > 0 ? <ul>{followUps.map((item) => <li key={item.id}>{item.question} <span>— {item.reviewerPersona}</span></li>)}</ul> : <p>No additional content-specific prompts were triggered.</p>}
          </div>
        ) : null}

        <div className={styles.fieldGroup}>
          <label className={styles.label} htmlFor="focus-notes">Session notes</label>
          <textarea id="focus-notes" className={styles.textarea} rows={3} value={notes} onChange={(event) => setNotes(event.currentTarget.value)} placeholder="Follow-ups to prepare, research tasks…" />
        </div>

        {statusMessage ? <p className={styles.helper} role="status">{statusMessage}</p> : null}

        <footer className={styles.focusFooter}>
          <button type="button" className={styles.quietButton} onClick={() => (onSkip ? onSkip() : advance())}>Skip</button>
          <button
            type="button"
            className={styles.quietButton}
            onClick={() => {
              markGapNotApplicable(record.id, gap.id);
              onMarkNotApplicable?.(gap.id);
              setStatusMessage("Marked not applicable for this session.");
              advance();
            }}
          >
            Mark not applicable
          </button>
          <button
            type="button"
            className={styles.quietButton}
            onClick={() => {
              pushResearchTask(record, gap, notes);
              setStatusMessage("Added to research queue (local).");
            }}
          >
            Add research task
          </button>
          <button type="button" className={styles.quietButton} onClick={() => setShowFollowUps((visible) => !visible)}>Ask for follow-up prompts</button>
          <button type="button" className={styles.quietButton} onClick={handleSaveDraft} disabled={!answer.trim()}>Save draft</button>
          <button type="button" className={styles.primaryButton} onClick={handleSave} disabled={!answer.trim() && !question}>Save & next</button>
        </footer>
      </div>
    </div>
  );
}
