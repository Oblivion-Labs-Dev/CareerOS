"use client";

import { useState } from "react";
import { answerQuestionGroup } from "@/lib/application-assistant-api";
import styles from "./pending-question-answers.module.css";

export type QuestionGroupRow = {
  question: string;
  headline?: string;
  variants?: string[];
  jobIds: string[];
  jobCount?: number;
  unblocksAlone?: number;
};

/**
 * The outstanding questions, answerable in place.
 *
 * One implementation, rendered in the Review tab. It used to live inside the
 * Night Batch card, which put a scrolling worklist directly above the Start
 * button — the card is a control, not a queue. The card now carries only a
 * one-line warning that links here.
 *
 * Ordering is by how many applications an answer actually finishes, then by
 * how many it appears in. Those are different numbers and the distinction
 * matters: the median blocked application waits on more than one question, so
 * a question "asked by 43 applications" can finish none of them on its own.
 * Sorting by the wrong one sends the user to work that unblocks nothing.
 */
export function PendingQuestionAnswers({
  groups,
  onAnswered,
  limit,
}: {
  groups: QuestionGroupRow[];
  onAnswered?: () => void;
  limit?: number;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answering, setAnswering] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const ordered = [...groups].sort(
    (a, b) =>
      (b.unblocksAlone ?? 0) - (a.unblocksAlone ?? 0) ||
      (b.jobCount ?? 0) - (a.jobCount ?? 0) ||
      a.question.localeCompare(b.question),
  );
  const rows = typeof limit === "number" ? ordered.slice(0, limit) : ordered;

  const submit = async (group: QuestionGroupRow) => {
    const value = (answers[group.question] || "").trim();
    if (!value) return;
    setAnswering(group.question);
    setNote(null);
    try {
      const result = await answerQuestionGroup({
        question: group.question,
        answer: value,
        variants: group.variants,
        jobIds: group.jobIds,
      });
      setNote(result.message);
      setAnswers((previous) => ({ ...previous, [group.question]: "" }));
      onAnswered?.();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "Could not save that answer");
    } finally {
      setAnswering(null);
    }
  };

  if (rows.length === 0) return null;

  return (
    <section className={styles.panel} aria-label="Questions holding applications">
      <header className={styles.head}>
        <h3>Answer once, unblock many</h3>
        <p>
          Sorted by how many applications each answer finishes. Answering here saves the
          response for every application that asks it.
        </p>
      </header>
      <ol className={styles.list}>
        {rows.map((group) => (
          <li key={group.question}>
            <div className={styles.meta}>
              {typeof group.unblocksAlone === "number" && group.unblocksAlone > 0 ? (
                <span className={styles.badge}>Finishes {group.unblocksAlone}</span>
              ) : (
                <span className={`${styles.badge} ${styles.badgeMuted}`}>
                  Asked by {group.jobCount ?? group.jobIds.length}
                </span>
              )}
              <span className={styles.hint}>{group.headline}</span>
            </div>
            <p className={styles.question}>{group.question}</p>
            <form
              className={styles.answerRow}
              onSubmit={(event) => {
                event.preventDefault();
                void submit(group);
              }}
            >
              <input
                type="text"
                aria-label={`Answer: ${group.question}`}
                placeholder="Answer once — applies everywhere it is asked"
                value={answers[group.question] || ""}
                onChange={(event) =>
                  setAnswers((previous) => ({ ...previous, [group.question]: event.target.value }))
                }
                disabled={answering === group.question}
              />
              <button
                type="submit"
                disabled={!(answers[group.question] || "").trim() || answering === group.question}
              >
                {answering === group.question ? "Saving…" : "Save"}
              </button>
            </form>
          </li>
        ))}
      </ol>
      {note && <p className={styles.note}>{note}</p>}
    </section>
  );
}
