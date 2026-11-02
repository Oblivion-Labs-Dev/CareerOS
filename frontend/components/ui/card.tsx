"use client";

import React from "react";
import styles from "./primitives.module.css";

export type CardStatus = "success" | "active" | "attention" | "danger" | "info" | "neutral";
export type CardVariant = "standard" | "interactive" | "status" | "metric" | "insight";
export type CardPadding = "none" | "compact" | "default";

export type CardProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: CardVariant;
  /** Only meaningful for variant="status" — paints the accent rail. */
  status?: CardStatus;
  padding?: CardPadding;
  selected?: boolean;
  /** Turns the card into a real button so keyboard users get it for free. */
  onActivate?: () => void;
};

/**
 * Cards carry most of CareerOS's information, so they're variants of one
 * language rather than ad-hoc rectangles: standard for content, interactive
 * for anything clickable, status for state-bearing rows, metric for figures,
 * and insight for AI-generated context.
 */
export function Card({
  variant = "standard",
  status = "neutral",
  padding = "default",
  selected = false,
  onActivate,
  className = "",
  children,
  ...rest
}: CardProps) {
  const isInteractive = variant === "interactive" || Boolean(onActivate);

  const classes = [
    styles.card,
    isInteractive ? styles.cardInteractive : "",
    variant === "status" ? styles.cardStatus : "",
    variant === "metric" ? styles.cardMetric : "",
    variant === "insight" ? styles.cardInsight : "",
    selected ? styles.cardSelected : "",
    padding === "default" && variant !== "metric" ? styles.cardPadded : "",
    padding === "compact" ? styles.cardCompact : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const statusAttr = variant === "status" ? { "data-status": status } : {};

  if (isInteractive && onActivate) {
    return (
      <button type="button" className={classes} onClick={onActivate} {...statusAttr} {...(rest as any)}>
        {children}
      </button>
    );
  }

  return (
    <div className={classes} {...statusAttr} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({
  eyebrow,
  title,
  action,
  className = "",
}: {
  eyebrow?: React.ReactNode;
  title?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`${styles.cardHeader} ${className}`}>
      <div>
        {eyebrow ? <div className={styles.cardEyebrow}>{eyebrow}</div> : null}
        {title ? <div className={styles.cardTitle}>{title}</div> : null}
      </div>
      {action}
    </div>
  );
}

export function CardBody({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`${styles.cardBody} ${className}`}>{children}</div>;
}

export function CardFooter({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`${styles.cardFooter} ${className}`}>{children}</div>;
}

/** A figure with its label — the number leads, the label supports it. */
export function MetricCard({
  label,
  value,
  hint,
  status = "info",
  className = "",
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  status?: CardStatus;
  className?: string;
}) {
  return (
    <Card variant="metric" className={className}>
      <div className={styles.metricLabel}>{label}</div>
      <div className={styles.metricValue} style={{ color: `var(--status-${status})` }}>
        {value}
      </div>
      {hint ? <div className={styles.metricHint}>{hint}</div> : null}
    </Card>
  );
}
