"use client";

import Link from "next/link";
import { discoverHref, type CareerWorkspacePrefs } from "@/lib/career-workspace";
import styles from "./minimal-dashboard.module.css";

type TodayActionsProps = {
  prefs: CareerWorkspacePrefs;
  freshMatchCount: number;
  followUpCount: number;
  awaitingDecisionCount: number;
};

export function TodayActions({ prefs, freshMatchCount, followUpCount, awaitingDecisionCount }: TodayActionsProps) {
  return (
    <section className={styles.todayGrid}>
      <article className={styles.todayCard}>
        <span className={styles.todayEyebrow}>Supply</span>
        <h2 className={styles.todayTitle}>Review fresh matches</h2>
        <p className={styles.todayCopy}>
          {freshMatchCount > 0
            ? `${freshMatchCount} strong matches from your latest scrape. Filter first, then score.`
            : "Run a scrape on Job Scraper to pull new roles into your inbox."}
        </p>
        <Link href={discoverHref(prefs)} className={styles.todayAction}>
          Open Job Scraper →
        </Link>
      </article>

      <article className={styles.todayCard}>
        <span className={styles.todayEyebrow}>Demand</span>
        <h2 className={styles.todayTitle}>Follow up & decide</h2>
        <p className={styles.todayCopy}>
          {followUpCount > 0
            ? `${followUpCount} application${followUpCount === 1 ? "" : "s"} may need a follow-up.`
            : "No follow-ups flagged right now."}
          {awaitingDecisionCount > 0
            ? ` ${awaitingDecisionCount} still awaiting your decision.`
            : ""}
        </p>
        <Link href="/dashboard#applications" className={styles.todayAction}>
          View pipeline →
        </Link>
      </article>
    </section>
  );
}
