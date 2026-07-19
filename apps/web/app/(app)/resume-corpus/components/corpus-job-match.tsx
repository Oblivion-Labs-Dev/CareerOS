"use client";

import { MetricCard, ScoreGauge, StatePanel } from "@arsenal/ui";
import { useMemo, useState } from "react";
import { CorpusEmptyState } from "@career-os/ui/corpus";
import type { CorpusRecord } from "../corpus-model";
import styles from "../resume-corpus.module.css";

interface CorpusJobMatchProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string) => void;
}

type CoverageKind = "explicit" | "inferred" | "unsupported" | "missing";

interface KeywordMatch {
  term: string;
  coverage: CoverageKind;
  recordIds: string[];
}

function extractKeywords(jobDescription: string): string[] {
  const words = jobDescription.toLowerCase().match(/[a-z][a-z0-9+#.-]{2,}/g) ?? [];
  const stop = new Set(["and", "the", "with", "for", "you", "will", "our", "that", "this", "have", "from"]);
  return [...new Set(words.filter((word) => !stop.has(word)))].slice(0, 40);
}

function analyzeMatch(records: CorpusRecord[], jobDescription: string) {
  const keywords = extractKeywords(jobDescription);
  const keywordMatches: KeywordMatch[] = keywords.map((term) => {
    const directMatches = records.filter((record) => {
      const directText = [
        record.title,
        record.currentBullet,
        record.summary,
        ...record.technologies,
        ...record.metrics.flatMap((metric) => [metric.name, metric.value]),
        ...record.evidence.flatMap((evidence) => [evidence.name, evidence.type]),
      ].join(" ").toLowerCase();
      return directText.includes(term);
    });
    const contextualMatches = records.filter((record) => {
      const contextualText = [
        record.technicalChallenge,
        record.architectureDecision,
        ...record.domains,
        ...record.concepts,
      ].join(" ").toLowerCase();
      return contextualText.includes(term);
    });
    let coverage: CoverageKind = "missing";
    if (directMatches.some((record) => {
      const matchingEvidence = record.evidence.some((evidence) =>
        `${evidence.name} ${evidence.type}`.toLowerCase().includes(term),
      );
      const matchingVerifiedMetric = record.metrics.some((metric) =>
        metric.verification === "verified" && `${metric.name} ${metric.value}`.toLowerCase().includes(term),
      );
      return matchingEvidence || matchingVerifiedMetric;
    })) coverage = "explicit";
    else if (directMatches.length > 0) coverage = "unsupported";
    else if (contextualMatches.length > 0) coverage = "inferred";
    return {
      term,
      coverage,
      recordIds: [...new Set([...directMatches, ...contextualMatches].map((record) => record.id))],
    };
  });

  const explicit = keywordMatches.filter((match) => match.coverage === "explicit");
  const unsupported = keywordMatches.filter((match) => match.coverage === "unsupported");
  const inferred = keywordMatches.filter((match) => match.coverage === "inferred");
  const missing = keywordMatches.filter((match) => match.coverage === "missing");
  const score = keywords.length === 0
    ? 0
    : Math.round(((explicit.length + inferred.length * 0.2) / keywords.length) * 100);

  const relevant = records
    .map((record) => {
      const hits = keywordMatches.filter((match) => match.recordIds.includes(record.id)).length;
      return { record, hits };
    })
    .filter(({ hits }) => hits > 0)
    .sort((left, right) => right.hits - left.hits || right.record.roastResistance - left.record.roastResistance)
    .slice(0, 8);

  return { score, explicit, inferred, unsupported, missing, relevant, keywordMatches };
}

export function CorpusJobMatch({ records, onSelectRecord }: CorpusJobMatchProps) {
  const [jobDescription, setJobDescription] = useState("");
  const [analyzed, setAnalyzed] = useState(false);

  const analysis = useMemo(
    () => (analyzed && jobDescription.trim() ? analyzeMatch(records, jobDescription) : null),
    [analyzed, jobDescription, records],
  );

  if (records.length === 0) {
    return (
      <CorpusEmptyState
        title="Add accomplishments before matching jobs"
        description="Job match compares your proven stories against a target description — not keyword stuffing."
      />
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Job Match</div>
          <h1>Analyze role fit with evidence</h1>
          <p>Distinguish explicit proof, inferred support, and missing requirements before tailoring your resume.</p>
        </div>
      </header>

      <div className={styles.splitLayout}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <h2>Target job description</h2>
            <p>Paste the full posting or requirements section.</p>
          </div>
          <textarea
            className={styles.textarea}
            rows={14}
            value={jobDescription}
            onChange={(event) => {
              setAnalyzed(false);
              setJobDescription(event.currentTarget.value);
            }}
            placeholder="Paste job description…"
            aria-label="Job description"
          />
          <div className={styles.workspaceActions}>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={!jobDescription.trim()}
              onClick={() => setAnalyzed(true)}
            >
              Analyze match
            </button>
          </div>
        </section>

        <section className={styles.panel}>
          {!analysis ? (
            <StatePanel
              kind="empty"
              title="No analysis yet"
              description="Paste a job description and analyze to see keyword coverage, gaps, and relevant accomplishments."
            />
          ) : (
            <>
              <div className={styles.matchScore}>
                <ScoreGauge value={analysis.score} label="Match score" size="lg" tone={analysis.score >= 70 ? "success" : analysis.score >= 45 ? "accent" : "danger"} />
              </div>

              <div className={styles.coverageGrid}>
                <div className={styles.coverageColumn}>
                  <h3>Explicit evidence ({analysis.explicit.length})</h3>
                  <div className={styles.keywordList}>
                    {analysis.explicit.map((match) => (
                      <span key={match.term} className={styles.keyword} data-coverage="explicit">{match.term}</span>
                    ))}
                  </div>
                </div>
                <div className={styles.coverageColumn}>
                  <h3>Inferred support ({analysis.inferred.length})</h3>
                  <div className={styles.keywordList}>
                    {analysis.inferred.map((match) => (
                      <span key={match.term} className={styles.keyword} data-coverage="inferred">{match.term}</span>
                    ))}
                  </div>
                </div>
                <div className={styles.coverageColumn}>
                  <h3>Explicit claim, no evidence ({analysis.unsupported.length})</h3>
                  <div className={styles.keywordList}>
                    {analysis.unsupported.map((match) => (
                      <span key={match.term} className={styles.keyword} data-coverage="unsupported">{match.term}</span>
                    ))}
                  </div>
                </div>
                <div className={styles.coverageColumn}>
                  <h3>Missing ({analysis.missing.length})</h3>
                  <div className={styles.keywordList}>
                    {analysis.missing.slice(0, 12).map((match) => (
                      <span key={match.term} className={styles.keyword} data-coverage="missing">{match.term}</span>
                    ))}
                  </div>
                </div>
                <div className={styles.coverageColumn}>
                  <h3>Relevant accomplishments</h3>
                  <div className={styles.compactList}>
                    {analysis.relevant.map(({ record, hits }) => (
                      <button key={record.id} type="button" className={styles.compactRow} onClick={() => onSelectRecord(record.id)}>
                        <span><strong>{record.title}</strong><span>{hits} keyword hits · {record.company}</span></span>
                        <span className={styles.readiness} data-readiness={record.readiness}>{record.readiness}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      {analysis ? (
        <div className={styles.metricsGrid}>
          <MetricCard label="Explicit keywords" value={String(analysis.explicit.length)} description="Backed by metrics or evidence" tone="success" />
          <MetricCard label="Unsupported claims" value={String(analysis.unsupported.length)} description="Explicitly stated, but no evidence is attached" tone="danger" />
          <MetricCard label="Inferred keywords" value={String(analysis.inferred.length)} description="Context suggests a relationship; the corpus does not state it directly" tone="accent" />
          <MetricCard label="Missing keywords" value={String(analysis.missing.length)} description="Not found in corpus" tone="danger" />
        </div>
      ) : null}
    </div>
  );
}
