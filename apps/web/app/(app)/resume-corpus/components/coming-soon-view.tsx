"use client";

import type { ComingSoonFeature, CorpusView } from "../corpus-navigation";
import styles from "../resume-corpus.module.css";

interface ComingSoonViewProps {
  feature: ComingSoonFeature;
  onNavigate: (view: CorpusView) => void;
}

export function ComingSoonView({ feature, onNavigate }: ComingSoonViewProps) {
  return (
    <section className={styles.comingSoonPage} aria-labelledby="coming-soon-title" data-testid="coming-soon-preview">
      <div className={styles.comingSoonHero}>
        <div className={styles.comingSoonLock} aria-hidden="true">
          <span />
        </div>
        <div className={styles.comingSoonHeroCopy}>
          <div className={styles.comingSoonEyebrow}>
            <span>Planned</span>
            <span className={styles.comingSoonBadge}>Coming soon</span>
          </div>
          <h1 id="coming-soon-title">{feature.label}</h1>
          <p>{feature.description}</p>
          <div className={styles.comingSoonNotice} role="status">
            This feature is planned but not yet available. Phase 1 is focused on making every accomplishment complete, credible, and reusable first.
          </div>
          <div className={styles.comingSoonActions}>
            <button type="button" className={styles.primaryButton} onClick={() => onNavigate("accomplishments")}>
              Work on accomplishments
            </button>
            <button type="button" className={styles.quietButton} onClick={() => onNavigate("overview")}>
              Return to overview
            </button>
          </div>
        </div>
      </div>

      <div className={styles.comingSoonPreviewGrid} aria-label={feature.label + " roadmap preview"}>
        <article className={styles.comingSoonPreviewCard}>
          <span className={styles.comingSoonCardIndex} aria-hidden="true">01</span>
          <div>
            <h2>What it will do</h2>
            <p>{feature.description}</p>
          </div>
        </article>
        <article className={styles.comingSoonPreviewCard}>
          <span className={styles.comingSoonCardIndex} aria-hidden="true">02</span>
          <div>
            <h2>Why it matters</h2>
            <p>{feature.why}</p>
          </div>
        </article>
        <article className={styles.comingSoonPreviewCard}>
          <span className={styles.comingSoonCardIndex} aria-hidden="true">03</span>
          <div>
            <h2>Estimated roadmap stage</h2>
            <p>{feature.stage}</p>
          </div>
        </article>
      </div>

      <div className={styles.comingSoonFoundation}>
        <div>
          <span className={styles.comingSoonFoundationLabel}>Built in the right order</span>
          <h2>One source of truth, many future outputs</h2>
          <p>
            The feature will build from the canonical problem, ownership, engineering story, metrics, impact, technologies, evidence, interview answers, missing information, and lessons already stored in CareerOS.
          </p>
        </div>
        <ol className={styles.comingSoonRoadmap} aria-label="CareerOS roadmap">
          <li data-current="true"><span>Now</span><strong>Core accomplishment corpus</strong></li>
          <li><span>Next</span><strong>Intelligence and review</strong></li>
          <li><span>Later</span><strong>Generation and career analytics</strong></li>
        </ol>
      </div>
    </section>
  );
}
