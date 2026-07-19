"use client";

import { MetricCard, ScoreGauge, SegmentedControl, StatePanel } from "@arsenal/ui";
import { useMemo, useState } from "react";
import { CorpusEmptyState } from "@career-os/ui/corpus";
import type { CorpusRecord } from "../corpus-model";
import { evaluateResumeBullet, mapReviewerConcern, summarizeBulletReadiness } from "../corpus-quality";
import { QualityStatusBadge } from "./corpus-quality-ui";
import styles from "../resume-corpus.module.css";

const BUILDER_STEPS = [
  "Target role",
  "Job description",
  "Company",
  "Experience",
  "Length",
  "Accomplishments",
  "Keywords",
  "Claims",
  "Preview",
  "Export",
] as const;

interface GeneratorInputs {
  targetCompany: string;
  targetRole: string;
  jobDescription: string;
  experienceLevel: string;
  tone: string;
  maxPages: number;
  selectedIds: string[];
}

interface CorpusResumeBuilderProps {
  records: CorpusRecord[];
  generatorInputs: GeneratorInputs;
  generatedResume: {
    content?: string;
    warnings?: string[];
    provenance?: "selected-records" | "generated-draft";
  } | null;
  generationError: string | null;
  generating: boolean;
  onInputsChange: (inputs: GeneratorInputs) => void;
  onGenerate: () => void;
  onSelectRecord: (recordId: string, sectionId?: string) => void;
  onCreate: () => void;
}

function rankRecords(records: CorpusRecord[], jobDescription: string): Array<CorpusRecord & { rankReason: string }> {
  const keywords = jobDescription.toLowerCase().split(/\W+/).filter((word) => word.length > 3);
  return records
    .map((record) => {
      const haystack = [
        record.title,
        record.currentBullet,
        record.summary,
        ...record.technologies,
        ...record.domains,
      ].join(" ").toLowerCase();
      const keywordHits = keywords.filter((word) => haystack.includes(word)).length;
      const score =
        (record.readiness === "ready" ? 30 : 0) +
        record.roastResistance * 0.25 +
        record.impactScore * 0.2 +
        keywordHits * 8 +
        record.metrics.length * 5;
      const rankReason =
        keywordHits > 0
          ? `${keywordHits} job-description keyword${keywordHits === 1 ? "" : "s"} matched`
          : record.readiness === "ready"
            ? "Resume-ready with strong evidence"
            : "Strong impact score and technical depth";
      return { ...record, score, rankReason };
    })
    .sort((left, right) => right.score - left.score)
    .slice(0, 12);
}

export function CorpusResumeBuilder({
  records,
  generatorInputs,
  generatedResume,
  generationError,
  generating,
  onInputsChange,
  onGenerate,
  onSelectRecord,
  onCreate,
}: CorpusResumeBuilderProps) {
  const [step, setStep] = useState(0);
  const [canvasView, setCanvasView] = useState<"resume" | "jd" | "keywords">("resume");
  const ranked = useMemo(
    () => rankRecords(records, generatorInputs.jobDescription),
    [generatorInputs.jobDescription, records],
  );

  const selectedRecords = records.filter((record) => generatorInputs.selectedIds.includes(record.id));
  const warnings = generatedResume?.warnings ?? [];
  const jobKeywords = useMemo(
    () => [...new Set(generatorInputs.jobDescription.toLowerCase().split(/\W+/).filter((word) => word.length > 3))],
    [generatorInputs.jobDescription],
  );
  const selectedText = selectedRecords
    .flatMap((record) => [record.title, record.currentBullet, record.summary, ...record.technologies, ...record.domains])
    .join(" ")
    .toLowerCase();
  const keywordCoverage = jobKeywords.length > 0
    ? Math.round((jobKeywords.filter((keyword) => selectedText.includes(keyword)).length / jobKeywords.length) * 100)
    : 0;

  if (records.length === 0) {
    return (
      <CorpusEmptyState
        title="No accomplishments to build from"
        description="Record structured career stories first, then generate a tailored resume from proven material."
        actionLabel="Create accomplishment"
        onAction={onCreate}
      />
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Resume Builder</div>
          <h1>Guided resume generation</h1>
          <p>Rank accomplishments by role relevance, evidence confidence, and keyword coverage — then preview an ATS-oriented plain-text canvas.</p>
        </div>
      </header>

      <div className={styles.stepper} role="tablist" aria-label="Resume builder steps">
        {BUILDER_STEPS.map((label, index) => (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={step === index}
            className={`${styles.step} ${step === index ? styles.stepActive : ""}`}
            onClick={() => setStep(index)}
          >
            {index + 1}. {label}
          </button>
        ))}
      </div>

      <div className={styles.splitLayout}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <h2>Configuration</h2>
            <p>Steps {step + 1} of {BUILDER_STEPS.length}</p>
          </div>
          <div className={styles.formStack}>
            {step <= 1 ? (
              <>
                <div className={styles.fieldGroup}>
                  <label className={styles.label} htmlFor="target-role">Target role</label>
                  <input
                    id="target-role"
                    className={styles.field}
                    value={generatorInputs.targetRole}
                    onChange={(event) => onInputsChange({ ...generatorInputs, targetRole: event.currentTarget.value })}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.label} htmlFor="job-description">Job description</label>
                  <textarea
                    id="job-description"
                    className={styles.textarea}
                    rows={8}
                    value={generatorInputs.jobDescription}
                    onChange={(event) => onInputsChange({ ...generatorInputs, jobDescription: event.currentTarget.value })}
                  />
                </div>
              </>
            ) : null}

            {step >= 2 && step <= 4 ? (
              <>
                <div className={styles.fieldGroup}>
                  <label className={styles.label} htmlFor="target-company">Target company</label>
                  <input
                    id="target-company"
                    className={styles.field}
                    value={generatorInputs.targetCompany}
                    onChange={(event) => onInputsChange({ ...generatorInputs, targetCompany: event.currentTarget.value })}
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.label} htmlFor="experience-level">Experience level</label>
                  <select
                    id="experience-level"
                    className={styles.field}
                    value={generatorInputs.experienceLevel}
                    onChange={(event) => onInputsChange({ ...generatorInputs, experienceLevel: event.currentTarget.value })}
                  >
                    {["Mid", "Senior", "Staff", "Principal"].map((level) => (
                      <option key={level} value={level}>{level}</option>
                    ))}
                  </select>
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.label} htmlFor="max-pages">Resume length (pages)</label>
                  <input
                    id="max-pages"
                    type="number"
                    min={1}
                    max={3}
                    className={styles.field}
                    value={generatorInputs.maxPages}
                    onChange={(event) => onInputsChange({ ...generatorInputs, maxPages: Number(event.currentTarget.value) })}
                  />
                </div>
              </>
            ) : null}

            {step >= 5 ? (
              <div className={styles.compactList}>
                {ranked.map((record) => {
                  const selected = generatorInputs.selectedIds.includes(record.id);
                  const readiness = evaluateResumeBullet(record);
                  const quality = summarizeBulletReadiness(record);
                  return (
                    <div key={record.id} className={styles.compactRow}>
                      <input
                        type="checkbox"
                        aria-label={`Include ${record.title}`}
                        checked={selected}
                        disabled={readiness.indicator === "not-recommended"}
                        onChange={() => {
                          const next = selected
                            ? generatorInputs.selectedIds.filter((id) => id !== record.id)
                            : [...generatorInputs.selectedIds, record.id];
                          onInputsChange({ ...generatorInputs, selectedIds: next });
                        }}
                      />
                      <span>
                        <strong>{record.title}</strong>
                        <span>{record.rankReason}</span>
                        <QualityStatusBadge status={quality.overallStatus} compact />
                        <span className={styles.resumeBulletIndicator} data-indicator={readiness.indicator} title={readiness.blockReason ?? readiness.message}>
                          {readiness.message}
                        </span>
                      </span>
                      <button type="button" className={styles.textButton} onClick={() => onSelectRecord(record.id, readiness.indicator === "missing-architecture" ? "architecture" : readiness.indicator === "weak-ownership" ? "ownership" : "overview")}>
                        Inspect
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : null}

            <div className={styles.workspaceActions}>
              <button type="button" className={styles.quietButton} disabled={step === 0} onClick={() => setStep((value) => value - 1)}>
                Back
              </button>
              {step < BUILDER_STEPS.length - 1 ? (
                <button type="button" className={styles.primaryButton} onClick={() => setStep((value) => value + 1)}>
                  Continue
                </button>
              ) : (
                <button type="button" className={styles.primaryButton} disabled={generating} onClick={onGenerate}>
                  {generating ? "Generating…" : "Generate resume"}
                </button>
              )}
            </div>
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <h2>Resume canvas</h2>
            <p>{selectedRecords.length} bullets selected · {generatorInputs.maxPages} page target</p>
          </div>

          <div className={styles.canvasToolbar}>
            <SegmentedControl
              label="Canvas view"
              value={canvasView}
              onValueChange={setCanvasView}
              size="sm"
              options={[
                { value: "resume", label: "Resume" },
                { value: "jd", label: "Job description" },
                { value: "keywords", label: "Keywords" },
              ]}
            />
            <ScoreGauge value={keywordCoverage} label="JD keyword coverage" size="sm" />
          </div>

          {warnings.length > 0 ? (
            <div className={styles.warningList}>
              {warnings.map((warning) => (
                <div key={warning} className={styles.warningRow}>{warning}</div>
              ))}
            </div>
          ) : null}

          {generationError ? (
            <StatePanel
              kind="error"
              title="Resume generation unavailable"
              description={generationError}
            />
          ) : null}

          {selectedRecords.some((record) => record.concerns.some((concern) => concern.status === "unanswered" || concern.status === "investigating")) ? (
            <div className={styles.warningList} role="status">
              {selectedRecords.flatMap((record) =>
                record.concerns
                  .filter((concern) => concern.status === "unanswered" || concern.status === "investigating")
                  .slice(0, 2)
                  .map((concern) => {
                    const mapped = mapReviewerConcern(record, concern);
                    return (
                      <button key={concern.id} type="button" className={styles.warningRow} onClick={() => onSelectRecord(record.id, "concerns")}>
                        <strong>{record.title}:</strong> {concern.reviewer} — {concern.concern}
                        {mapped.question ? ` Question: ${mapped.question}` : ""}
                        {" "}({mapped.resumeImpact} impact · {mapped.resolutionStatus})
                      </button>
                    );
                  }),
              )}
            </div>
          ) : null}

          <article className={styles.resumeCanvas} aria-label="Resume preview">
            {canvasView === "resume" ? (
              <>
                <h2>{generatorInputs.targetRole || "Target role"}</h2>
                <h3>Experience</h3>
                <ul>
                  {generatedResume?.content
                    ? generatedResume.content.split("\n").filter(Boolean).map((bullet, index) => (
                        <li key={index}>{bullet}</li>
                      ))
                    : selectedRecords.map((record) => {
                        const readiness = evaluateResumeBullet(record);
                        const quality = summarizeBulletReadiness(record);
                        return (
                          <li key={record.id}>
                            {record.currentBullet || record.summary}
                            <QualityStatusBadge status={quality.overallStatus} compact />
                            <span className={styles.resumeBulletIndicator} data-indicator={readiness.indicator} title={readiness.blockReason ?? readiness.message}>
                              {readiness.message}
                            </span>
                          </li>
                        );
                      })}
                </ul>
              </>
            ) : canvasView === "jd" ? (
              <>
                <h2>Job description</h2>
                <p>{generatorInputs.jobDescription || "Add a job description in step 2 to compare coverage."}</p>
              </>
            ) : (
              <>
                <h2>Keyword coverage</h2>
                <p>{selectedRecords.length} selected stories contributing to keyword overlap.</p>
              </>
            )}
          </article>

          {!generatedResume && selectedRecords.length === 0 ? (
            <StatePanel
              kind="empty"
              title="Select accomplishments to preview"
              description="Recommended stories appear on the left once you add a job description."
            />
          ) : null}
        </section>
      </div>

          <div className={styles.metricsGrid}>
        <MetricCard label="Selected bullets" value={String(selectedRecords.length)} description="Included in this draft" tone="accent" />
        <MetricCard label="Verified metrics" value={String(selectedRecords.reduce((sum, record) => sum + record.metrics.filter((metric) => metric.verification === "verified").length, 0))} description="Quantified claims with proof" tone="success" />
        <MetricCard label="Reviewer risk" value={String(selectedRecords.reduce((sum, record) => sum + record.concerns.filter((concern) => concern.status === "unanswered").length, 0))} description="Open concerns in selection" tone="danger" />
      </div>

      <section className={styles.panel} aria-labelledby="export-heading">
        <div className={styles.panelHeader}>
          <div>
            <h2 id="export-heading">Export</h2>
            <p>Copy plain text or download a text draft. PDF/DOCX export comes after layout validation.</p>
          </div>
          <div className={styles.workspaceActions}>
            <button
              type="button"
              className={styles.quietButton}
              disabled={selectedRecords.length === 0 && !generatedResume?.content}
              onClick={async () => {
                const text = generatedResume?.content
                  || selectedRecords.map((record) => record.currentBullet || record.summary).join("\n\n");
                try {
                  await navigator.clipboard.writeText(text);
                } catch {
                  // Clipboard can fail in non-secure contexts; download remains available.
                }
              }}
            >
              Copy bullets
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={selectedRecords.length === 0 && !generatedResume?.content}
              onClick={() => {
                const text = [
                  generatorInputs.targetRole || "Target role",
                  "",
                  "Experience",
                  generatedResume?.content
                    || selectedRecords.map((record) => `• ${record.currentBullet || record.summary}`).join("\n"),
                ].join("\n");
                const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
                const url = URL.createObjectURL(blob);
                const anchor = document.createElement("a");
                anchor.href = url;
                anchor.download = `${(generatorInputs.targetRole || "resume").replace(/\s+/g, "-").toLowerCase()}.txt`;
                anchor.click();
                URL.revokeObjectURL(url);
              }}
            >
              Download .txt
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
