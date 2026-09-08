"use client";

import React from "react";
import styles from "./primitives.module.css";

export type StatusTone = "success" | "active" | "attention" | "danger" | "info" | "neutral";

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  tone?: StatusTone;
  /** Shows a status dot; `live` makes it breathe for genuinely active state. */
  dot?: boolean;
  live?: boolean;
};

/**
 * Status is always colour + text (and optionally a dot) — never colour alone,
 * so it survives colour-blindness and greyscale.
 */
export function Badge({ tone = "neutral", dot = false, live = false, className = "", children, ...rest }: BadgeProps) {
  return (
    <span
      className={`${styles.badge} ${live ? styles.badgeLive : ""} ${className}`}
      data-tone={tone}
      {...rest}
    >
      {(dot || live) && <span className={styles.badgeDot} aria-hidden />}
      {children}
    </span>
  );
}

export type SkeletonProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: "text" | "title" | "block";
  width?: string | number;
  height?: string | number;
};

/** Shape-matched placeholder — avoids the jolt of a blank panel snapping full. */
export function Skeleton({ variant = "text", width, height, className = "", style, ...rest }: SkeletonProps) {
  const variantClass =
    variant === "title" ? styles.skeletonTitle : variant === "block" ? styles.skeletonBlock : styles.skeletonText;
  return (
    <div
      className={`${styles.skeleton} ${variantClass} ${className}`}
      style={{ width, height, ...style }}
      aria-hidden
      {...rest}
    />
  );
}

/** Several skeleton lines with natural width variation. */
export function SkeletonText({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={className} style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }} aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? "60%" : "100%"} />
      ))}
    </div>
  );
}

export type EmptyStateProps = {
  icon?: React.ReactNode;
  title: React.ReactNode;
  /** Say why it's empty and what happens next — never just "No data". */
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
};

export function EmptyState({ icon, title, description, actions, className = "" }: EmptyStateProps) {
  return (
    <div className={`${styles.empty} ${className}`} role="status">
      {icon ? <div className={styles.emptyIcon}>{icon}</div> : null}
      <div className={styles.emptyTitle}>{title}</div>
      {description ? <p className={styles.emptyBody}>{description}</p> : null}
      {actions ? <div className={styles.emptyActions}>{actions}</div> : null}
    </div>
  );
}

export type TabItem = { id: string; label: React.ReactNode; count?: number; icon?: React.ReactNode };

export function Tabs({
  items,
  value,
  onChange,
  className = "",
  ariaLabel,
}: {
  items: TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div className={`${styles.tabs} ${className}`} role="tablist" aria-label={ariaLabel}>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="tab"
          aria-selected={value === item.id}
          className={`${styles.tab} ${value === item.id ? styles.tabActive : ""}`}
          onClick={() => onChange(item.id)}
        >
          {item.icon}
          {item.label}
          {typeof item.count === "number" && item.count > 0 ? <Badge tone="attention">{item.count}</Badge> : null}
        </button>
      ))}
    </div>
  );
}
