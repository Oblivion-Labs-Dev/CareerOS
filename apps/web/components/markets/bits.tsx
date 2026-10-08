"use client";

import type { ReactNode } from "react";
import { timeAgo, STATUS_LABEL } from "./format";
import type { CompanyH1B, H1BStrength, MarketCompany, StatusBucket } from "./types";
import styles from "./markets.module.css";

export function Tip({ children, body, className }: { children: ReactNode; body: ReactNode; className?: string }) {
  return (
    <span className={`${styles.tip} ${className ?? ""}`}>
      {children}
      <span className={styles.tipBody} role="tooltip">{body}</span>
    </span>
  );
}

const H1B_TEXT: Record<H1BStrength, string> = { strong: "Strong", moderate: "Moderate", weak: "Unknown" };
export const H1B_NOTE = "Company-level sponsorship history. Individual roles may differ.";

export function H1BMark({ strength, h1b }: { strength: H1BStrength; h1b?: CompanyH1B }) {
  return (
    <Tip
      className={styles.h1b}
      body={
        <>
          <div>{H1B_NOTE}</div>
          {h1b?.evidence ? <div style={{ marginTop: ".4rem" }}>{h1b.evidence}</div> : null}
          {h1b?.source ? <div style={{ marginTop: ".3rem", color: "var(--muted)" }}>Source: {h1b.source}</div> : null}
        </>
      }
    >
      <span data-s={strength} className={styles.h1b}>
        <span className={styles.h1bBars} aria-hidden><i /><i /><i /></span>
        {H1B_TEXT[strength]}
      </span>
    </Tip>
  );
}

export function StatusDot({ status }: { status: StatusBucket }) {
  return <span className={styles.dot} data-s={status} aria-hidden />;
}

export function SourceTip({ company }: { company: MarketCompany }) {
  const c = company.career;
  return (
    <dl>
      <dt>Source</dt><dd>{c.label}{c.method ? ` · ${c.method.replace(/_/g, " ")}` : ""}</dd>
      <dt>URL</dt><dd>{c.url || "No official career URL"}</dd>
      <dt>Last success</dt><dd>{c.lastSuccessAt ? timeAgo(c.lastSuccessAt) : "never"}</dd>
      <dt>Last attempt</dt><dd>{c.lastAttemptAt ? timeAgo(c.lastAttemptAt) : "never"}</dd>
      {c.failureReason ? (<><dt>Reason</dt><dd>{c.failureReason}</dd></>) : null}
      {company.jobs.scopeLabel ? (<><dt>Coverage</dt><dd>{company.jobs.scopeLabel}</dd></>) : null}
    </dl>
  );
}

export function statusText(status: StatusBucket, sourceType: string): string {
  if (status === "manual") {
    if (sourceType === "BLOCKED") return "Blocked";
    if (sourceType === "BROWSER") return "Browser";
    if (sourceType === "UNKNOWN") return "Unknown";
  }
  return STATUS_LABEL[status];
}
