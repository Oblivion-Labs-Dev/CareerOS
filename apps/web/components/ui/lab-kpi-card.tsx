"use client";

import Link from "next/link";
import { useState, type CSSProperties, type ReactNode } from "react";
import styles from "./lab-kpi-card.module.css";

export type LabAccent = "blue" | "green" | "orange" | "purple" | "gold";

type LabKpiCardProps = {
  label: string;
  /** Rendered as raised "clay" characters; null shows a muted dash (unknown). */
  value: string | number | null;
  icon: ReactNode;
  accent: LabAccent;
  /** One short line under the number. */
  hint?: ReactNode;
  /** Optional real 0–1 ratio drawn as a thin meter (never a made-up trend). */
  meter?: number | null;
  /** Back face: eyebrow, headline and detail derived from real data. */
  insight: { eyebrow?: string; headline: string; detail?: string };
  /** Optional "Read full" style link on the back face. */
  action?: { href: string; label: string };
  /** Entry stagger in ms. */
  delay?: number;
};

/**
 * Flip KPI card ported from the Orchestrator Analytics Lab: clay digits on a
 * layered face, flipping to a single insight on hover, keyboard focus or tap.
 * Reduced motion swaps the 3D flip for a crossfade.
 */
export function LabKpiCard({ label, value, icon, accent, hint, meter, insight, action, delay = 0 }: LabKpiCardProps) {
  const [flipped, setFlipped] = useState(false);
  const text = value == null ? null : String(value);
  const ratio = meter == null || Number.isNaN(meter) ? null : Math.max(0, Math.min(1, meter));

  return (
    <div
      className={styles.card}
      data-accent={accent}
      data-flipped={flipped}
      style={{ "--delay": `${delay}ms` } as CSSProperties}
      role="button"
      tabIndex={0}
      aria-pressed={flipped}
      aria-label={`${label}: ${text ?? "unknown"}. ${insight.headline}${insight.detail ? `. ${insight.detail}` : ""}`}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a")) return;
        setFlipped((f) => !f);
      }}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setFlipped((f) => !f);
        } else if (e.key === "Escape") {
          setFlipped(false);
        }
      }}
      onMouseLeave={() => setFlipped(false)}
      onBlur={(e) => {
        // Keep the card turned while focus moves onto its own back-face link.
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFlipped(false);
      }}
    >
      <div className={`${styles.face} ${styles.front}`} aria-hidden="true">
        <div className={styles.top}>
          <span>{label}</span>
          <span className={styles.icon}>{icon}</span>
        </div>
        <span className={styles.number}>
          {text == null ? (
            <span className={styles.unknown}>—</span>
          ) : (
            text.split("").map((ch, i) => (
              <span key={i} className={styles.digit} style={{ "--i": i } as CSSProperties}>
                {ch}
              </span>
            ))
          )}
        </span>
        {hint ? <small className={styles.hint}>{hint}</small> : null}
        {ratio != null ? (
          <span className={styles.meter}>
            <i style={{ transform: `scaleX(${ratio})` }} />
          </span>
        ) : null}
      </div>
      <div className={`${styles.face} ${styles.back}`} aria-hidden={!flipped}>
        <span className={styles.eyebrow}>{insight.eyebrow ?? "Insight"}</span>
        <strong>{insight.headline}</strong>
        {insight.detail ? <small>{insight.detail}</small> : null}
        {action ? (
          <Link className={styles.read} href={action.href} tabIndex={flipped ? 0 : -1} onClick={(e) => e.stopPropagation()}>
            {action.label} →
          </Link>
        ) : null}
      </div>
    </div>
  );
}

/** Classic / Lab pill switch for the metric card look. */
export function CardStyleSwitch({
  value,
  onChange,
}: {
  value: "classic" | "lab";
  onChange: (next: "classic" | "lab") => void;
}) {
  return (
    <div className={styles.switch} role="radiogroup" aria-label="Metric card style">
      {(["classic", "lab"] as const).map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={value === option}
          data-active={value === option}
          onClick={() => onChange(option)}
        >
          {option === "classic" ? "Classic" : "Lab"}
        </button>
      ))}
    </div>
  );
}
