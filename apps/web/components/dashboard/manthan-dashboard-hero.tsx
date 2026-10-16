"use client";

import Link from "next/link";
import styles from "./manthan-dashboard-hero.module.css";

type ManthanDashboardHeroProps = {
  discoverTotal?: number;
  strongMatches?: number;
  applicationsCount?: number;
  candidateName?: string;
  targetRole?: string;
  onLaunchOnboarding?: () => void;
};

export function ManthanDashboardHero({
  discoverTotal = 74,
  strongMatches = 12,
  applicationsCount = 0,
  candidateName,
  targetRole = "Senior Software Engineer",
  onLaunchOnboarding,
}: ManthanDashboardHeroProps) {
  const firstName = candidateName ? candidateName.split(" ")[0] : null;

  return (
    <section className={styles.hero} aria-label="CareerOS Intelligence Overview">
      <div className={styles.copy}>
        <p className={styles.eyebrow}>
          <span className={styles.eyebrowSanskrit} lang="sa">मन्थन</span>
          <span className={styles.eyebrowDot} />
          <span>AUTONOMOUS CAREER DISCOVERY</span>
        </p>

        <h1 className={styles.title}>
          Hundreds of roles scouted overnight.{" "}
          <em>Targeted applications by morning.</em>
        </h1>

        <p className={styles.lede}>
          {firstName ? `Welcome, ${firstName}. ` : ""}
          Every night CareerOS sweeps live engineering portals, evaluates ATS relevancy against your
          verified experience, and queues tailored applications with precision.
        </p>

        <div className={styles.actions}>
          <Link href="/autopilot" className={styles.primaryBtn}>
            <span>Autopilot Engine</span>
            <span aria-hidden="true">→</span>
          </Link>
          <Link href="/jobs" className={styles.secondaryBtn}>
            <span>Explore Matched Roles ({discoverTotal})</span>
          </Link>
          {onLaunchOnboarding && (
            <button
              type="button"
              onClick={onLaunchOnboarding}
              className={styles.secondaryBtn}
              title="Review work authorization, clearance, and compensation settings"
            >
              <span>Onboarding Wizard</span>
            </button>
          )}
        </div>
      </div>

      <div className={styles.stageFlow}>
        <div className={styles.lightStream}>
          <span className={styles.lightPulse} />
        </div>

        <div className={styles.flowTrack}>
          {/* Stage 1: Sources & Discovery */}
          <div className={styles.stageCard}>
            <span className={styles.stageIndex}>01 · SCOUTED</span>
            <h3 className={styles.stageHeading}>Discovery</h3>
            <p className={styles.stageDetail}>DocuSign, Oracle, Ashby & Greenhouse</p>
            <div className={styles.stageMetric}>{discoverTotal} roles</div>
          </div>

          {/* Stage 2: Intelligence & Fit */}
          <div className={styles.stageCard}>
            <span className={styles.stageIndex}>02 · FIT MATRIX</span>
            <h3 className={styles.stageHeading}>Intelligence</h3>
            <p className={styles.stageDetail}>ATS & accomplishments weighted</p>
            <div className={styles.stageMetric}>{strongMatches} strong fits</div>
          </div>

          {/* Stage 3: Dispatched & Pipeline */}
          <div className={styles.stageCard}>
            <span className={styles.stageIndex}>03 · PIPELINE</span>
            <h3 className={styles.stageHeading}>Action</h3>
            <p className={styles.stageDetail}>Verified submissions & active queue</p>
            <div className={styles.stageMetric}>{applicationsCount} applications</div>
          </div>
        </div>

        <div className={styles.caption}>
          Target: <strong style={{ color: "var(--hero-fg)" }}>{targetRole}</strong> · Paced live submissions
        </div>
      </div>
    </section>
  );
}
