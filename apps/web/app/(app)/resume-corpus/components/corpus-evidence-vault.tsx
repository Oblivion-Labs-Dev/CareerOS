"use client";

import { useMemo, useState } from "react";
import { CorpusEmptyState, EvidenceViewer, FilterChip } from "@career-os/ui/corpus";
import type { CorpusRecord } from "../corpus-model";
import styles from "../resume-corpus.module.css";

interface CorpusEvidenceVaultProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string) => void;
}

export function CorpusEvidenceVault({ records, onSelectRecord }: CorpusEvidenceVaultProps) {
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const evidenceItems = useMemo(
    () =>
      records.flatMap((record) =>
        record.evidence.map((item) => ({
          ...item,
          recordTitle: record.title,
          recordId: record.id,
        })),
      ),
    [records],
  );

  const types = useMemo(() => [...new Set(evidenceItems.map((item) => item.type))], [evidenceItems]);
  const filtered = evidenceItems.filter((item) => typeFilter === "all" || item.type === typeFilter);
  const recordsWithoutEvidence = records.filter((record) => record.evidence.length === 0);

  if (records.length === 0) {
    return (
      <CorpusEmptyState
        title="No evidence yet"
        description="Evidence makes claims defensible — link RFCs, dashboards, PRs, and artifacts to accomplishments."
      />
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Evidence</div>
          <h1>Proof library</h1>
          <p>Every linked artifact strengthens reviewer confidence and interview answers.</p>
        </div>
      </header>

      <div className={styles.metricsGrid}>
        <div className={styles.panel}>
          <div className={styles.panelHeader}><h3>{evidenceItems.length}</h3><p>Total evidence items</p></div>
        </div>
        <div className={styles.panel}>
          <div className={styles.panelHeader}><h3>{records.filter((record) => record.evidence.length > 0).length}</h3><p>Accomplishments with proof</p></div>
        </div>
        <div className={styles.panel}>
          <div className={styles.panelHeader}><h3>{recordsWithoutEvidence.length}</h3><p>Stories missing evidence</p></div>
        </div>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.toolbarGroup}>
          <FilterChip label="All types" active={typeFilter === "all"} count={evidenceItems.length} onClick={() => setTypeFilter("all")} />
          {types.map((type) => (
            <FilterChip
              key={type}
              label={type}
              active={typeFilter === type}
              count={evidenceItems.filter((item) => item.type === type).length}
              onClick={() => setTypeFilter(type)}
            />
          ))}
        </div>
      </div>

      <section className={styles.panel}>
        <div className={styles.panelHeader}>
          <h2>Linked evidence</h2>
          <p>{filtered.length} item{filtered.length === 1 ? "" : "s"}</p>
        </div>
        <EvidenceViewer
          items={filtered}
          onSelectRecord={(title) => {
            const match = records.find((record) => record.title === title);
            if (match) onSelectRecord(match.id);
          }}
        />
      </section>

      {recordsWithoutEvidence.length > 0 ? (
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <h2>Missing evidence opportunities</h2>
            <p>These accomplishments would benefit most from linked proof.</p>
          </div>
          <div className={styles.compactList}>
            {recordsWithoutEvidence.map((record) => (
              <button key={record.id} type="button" className={styles.compactRow} onClick={() => onSelectRecord(record.id)}>
                <span><strong>{record.title}</strong><span>{record.company}</span></span>
                <span className={styles.statusTag}>No evidence</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
