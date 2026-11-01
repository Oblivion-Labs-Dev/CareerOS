"use client";

import Link from "next/link";
import { useState, type CSSProperties, type ReactNode } from "react";
import { useCountUp } from "@/hooks/use-count-up";
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
  /** Slide-in panel: eyebrow, headline, detail and optional figure rows, all from real data. */
  insight: { eyebrow?: string; headline: string; detail?: string; rows?: { label: string; value: string }[] };
  /** Optional "Read full" style link on the back face. */
  action?: { href: string; label: string };
  /** Entry stagger in ms. */
  delay?: number;
};

/**
 * Lab KPI card: clay digits on a matte face. On hover, keyboard focus or tap a
 * detail panel slides in from the right inside the same card. Reduced motion
 * swaps the slide for a crossfade.
 */
export function LabKpiCard({ label, value, icon, accent, hint, meter, insight, action, delay = 0 }: LabKpiCardProps) {
  const [open, setOpen] = useState(false);
  const text = value == null ? null : String(value);
  // Plain figures ("765", "8%") climb from zero on load; anything else renders as given.
  const figure = text == null ? null : /^(\d+(?:\.\d+)?)(%?)$/.exec(text);
  const decimals = figure?.[1].split(".")[1]?.length ?? 0;
  const counted = useCountUp(figure ? Number(figure[1]) : null, { delayMs: delay + 120, decimals });
  const shown = figure && counted != null ? `${counted.toFixed(decimals)}${figure[2]}` : text;
  const ratio = meter == null || Number.isNaN(meter) ? null : Math.max(0, Math.min(1, meter));

  return (
    <div
      className={styles.card}
      data-accent={accent}
      data-open={open}
      style={{ "--delay": `${delay}ms` } as CSSProperties}
      role="button"
      tabIndex={0}
      aria-expanded={open}
      aria-label={`${label}: ${text ?? "unknown"}. ${insight.headline}${insight.detail ? `. ${insight.detail}` : ""}${insight.rows?.length ? `. ${insight.rows.map((r) => `${r.label} ${r.value}`).join(", ")}` : ""}`}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a")) return;
        setOpen((f) => !f);
      }}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          setOpen((f) => !f);
        } else if (e.key === "Escape") {
          setOpen(false);
        }
      }}
      onMouseLeave={() => setOpen(false)}
      onBlur={(e) => {
        // Keep the panel open while focus moves onto its own link.
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <div className={styles.frame}>
      <div className={`${styles.face} ${styles.front}`} aria-hidden="true">
        <div className={styles.top}>
          <span>{label}</span>
          <span className={styles.icon}>{icon}</span>
        </div>
        <span className={styles.number}>
          {shown == null ? (
            <span className={styles.unknown}>—</span>
          ) : (
            shown.split("").map((ch, i) => (
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
      <div className={`${styles.face} ${styles.back}`} aria-hidden={!open}>
        <span className={styles.eyebrow}>{insight.eyebrow ?? "Insight"}</span>
        <strong>{insight.headline}</strong>
        {insight.detail ? <small>{insight.detail}</small> : null}
        {insight.rows?.length ? (
          <ul className={styles.rows}>
            {insight.rows.map((row) => (
              <li key={row.label}>
                <span>{row.label}</span>
                <b>{row.value}</b>
              </li>
            ))}
          </ul>
        ) : null}
        {action ? (
          <Link className={styles.read} href={action.href} tabIndex={open ? 0 : -1} onClick={(e) => e.stopPropagation()}>
            {action.label} →
          </Link>
        ) : null}
      </div>
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
