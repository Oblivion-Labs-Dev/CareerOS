"use client";

import { useState } from "react";
import styles from "../resume-corpus.module.css";

const TEMPLATE_CATALOG = [
  { id: "staff-engineering", name: "Staff engineering", pages: "2", audience: "Platform / infrastructure", status: "Ready", emphasis: "Architecture, scale, multi-team leverage" },
  { id: "senior-backend", name: "Senior backend", pages: "1", audience: "Product engineering", status: "Ready", emphasis: "Delivery, ownership, measurable outcomes" },
  { id: "ml-infra", name: "ML infrastructure", pages: "2", audience: "Research platform teams", status: "Draft", emphasis: "Evaluation systems, reliability, cost control" },
  { id: "leadership-heavy", name: "Leadership-heavy", pages: "2", audience: "Engineering manager track", status: "Draft", emphasis: "Influence, mentorship, org impact" },
  { id: "ats-minimal", name: "ATS minimal", pages: "1", audience: "High-volume applications", status: "Ready", emphasis: "Keyword clarity, short bullets, verified metrics" },
] as const;

interface CorpusTemplatesProps {
  onUseTemplate?: (templateId: string, maxPages: number) => void;
}

export function CorpusTemplates({ onUseTemplate }: CorpusTemplatesProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = TEMPLATE_CATALOG.find((template) => template.id === selectedId);

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Templates</div>
          <h1>Resume templates</h1>
          <p>Configurable layouts and section schemas — not hardcoded to one profession or company.</p>
        </div>
      </header>

      <div className={styles.panel}>
        <div className={styles.panelHeader}>
          <h2>Templates use your corpus data</h2>
          <p>Selecting a template controls section order, bullet density, and reviewer emphasis — accomplishments come from your knowledge system.</p>
        </div>
      </div>

      <div className={styles.cardGrid}>
        {TEMPLATE_CATALOG.map((template) => (
          <article key={template.id} className={styles.accomplishmentCard}>
            <div className={styles.cardBody}>
              <div className={styles.cardTopline}>
                <span className={styles.companyLabel}>{template.pages} page{template.pages === "1" ? "" : "s"}</span>
                <span className={styles.readiness} data-readiness={template.status === "Ready" ? "ready" : "draft"}>{template.status}</span>
              </div>
              <h3>{template.name}</h3>
              <p>{template.audience}</p>
              <p className={styles.helper}>{template.emphasis}</p>
              <div className={styles.cardFooter}>
                <button type="button" className={styles.textButton} onClick={() => setSelectedId(template.id)}>
                  Preview layout
                </button>
                <button
                  type="button"
                  className={styles.primaryButton}
                  onClick={() => onUseTemplate?.(template.id, Number(template.pages))}
                >
                  Use template
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {selected ? (
        <section className={styles.panel} aria-labelledby="template-preview-heading">
          <div className={styles.panelHeader}>
            <div>
              <h2 id="template-preview-heading">{selected.name} layout</h2>
              <p>{selected.pages}-page canvas · Emphasis: {selected.emphasis}</p>
            </div>
            <button type="button" className={styles.quietButton} onClick={() => setSelectedId(null)}>Close preview</button>
          </div>
          <ol className={styles.recordList}>
            <li className={styles.recordRow}><span className={styles.actionNumber}>01</span><span className={styles.rowCopy}><strong>Header</strong><span>Name, positioning, target role</span></span></li>
            <li className={styles.recordRow}><span className={styles.actionNumber}>02</span><span className={styles.rowCopy}><strong>Selected experience</strong><span>Ranked accomplishments from the corpus</span></span></li>
            <li className={styles.recordRow}><span className={styles.actionNumber}>03</span><span className={styles.rowCopy}><strong>Skills & evidence</strong><span>Depth-backed skills and verified metrics only</span></span></li>
            <li className={styles.recordRow}><span className={styles.actionNumber}>04</span><span className={styles.rowCopy}><strong>ATS safety check</strong><span>Unsupported claims and overflow warnings</span></span></li>
          </ol>
          <button
            type="button"
            className={styles.primaryButton}
            onClick={() => onUseTemplate?.(selected.id, Number(selected.pages))}
          >
            Continue in Resume Builder
          </button>
        </section>
      ) : null}
    </div>
  );
}
