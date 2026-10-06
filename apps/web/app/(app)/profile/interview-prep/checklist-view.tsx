"use client";

import { useEffect, useState } from "react";
import styles from "./checklist.module.css";

export type ChecklistItem = { id: string; text: string; detail: string };
export type ChecklistSection = { id: string; title: string; items: ChecklistItem[] };
export type InterviewChecklist = { title: string; basis: string; sections: ChecklistSection[] };

const STORAGE_KEY = "careeros-interview-prep-checks";

function readChecks(): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    return parsed as Record<string, boolean>;
  } catch {
    return {};
  }
}

export function InterviewChecklistView({ checklist }: { checklist: InterviewChecklist }) {
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const items = checklist.sections.flatMap((section) => section.items);
  const done = items.filter((item) => checks[item.id]).length;

  useEffect(() => {
    setChecks(readChecks());
  }, []);

  function toggle(id: string) {
    setChecks((current) => {
      const next = { ...current, [id]: !current[id] };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Profile · Interview</p>
        <h1>{checklist.title}</h1>
        <p>{checklist.basis}</p>
        <p className={styles.progress} role="status">{done} of {items.length} prepared</p>
      </header>
      {checklist.sections.map((section) => (
        <section key={section.id} className={styles.section} aria-labelledby={`prep-${section.id}`}>
          <h2 id={`prep-${section.id}`}>{section.title}</h2>
          <ul>
            {section.items.map((item) => (
              <li key={item.id}>
                <label>
                  <input
                    type="checkbox"
                    checked={Boolean(checks[item.id])}
                    onChange={() => toggle(item.id)}
                  />
                  <span>
                    <strong>{item.text}</strong>
                    <small>{item.detail}</small>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
