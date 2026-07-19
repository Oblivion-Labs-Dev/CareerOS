"use client";

import { InfoTooltip, StatusMarker, type StatusMarkerTone } from "@arsenal/ui";
import { useEffect, useMemo, useState } from "react";
import type { CorpusRecord, CorpusQuestionView } from "../corpus-model";
import {
  buildGapMap,
  buildResearchQueue,
  dimensionStatus,
  evaluateQuestionQuality,
  GAP_CATEGORIES,
  gapCategoryField,
  generateMissingQuestions,
  HEATMAP_DIMENSIONS,
  rankPriorityItems,
  summarizeBulletReadiness,
  type GapCategoryId,
  type GapItem,
  type GeneratedQuestion,
  type PriorityItem,
  type QualityStatus,
  type ResearchItem,
} from "../corpus-quality";
import styles from "../resume-corpus.module.css";

function impactRank(value: "high" | "medium" | "low"): number {
  return value === "high" ? 3 : value === "medium" ? 2 : 1;
}

function statusRank(status: QualityStatus): number {
  const order: QualityStatus[] = ["missing", "needs-verification", "weak", "partial", "strong", "interview-ready", "not-applicable"];
  return order.indexOf(status);
}

export const QUALITY_STATUS_LABEL: Record<QualityStatus, string> = {
  missing: "Missing",
  weak: "Needs detail",
  partial: "Partial",
  strong: "Strong",
  "interview-ready": "Interview ready",
  "not-applicable": "Not applicable",
  "needs-verification": "Verify",
};

export const QUALITY_STATUS_ICON: Record<QualityStatus, string> = {
  missing: "○",
  weak: "△",
  partial: "◐",
  strong: "●",
  "interview-ready": "✓",
  "not-applicable": "—",
  "needs-verification": "?",
};

const QUALITY_STATUS_DESCRIPTION: Record<QualityStatus, string> = {
  missing: "Required information or an answer is absent.",
  weak: "An answer exists but needs specific supporting detail.",
  partial: "Useful information exists, but important parts remain incomplete.",
  strong: "The information is clear, specific, and credible.",
  "interview-ready": "The answer is complete, supported, and practiced for follow-up questions.",
  "not-applicable": "This category is intentionally excluded from readiness calculations.",
  "needs-verification": "A claim, source, or metric must be validated before use.",
};

const QUALITY_STATUS_TONE: Record<QualityStatus, StatusMarkerTone> = {
  missing: "danger",
  weak: "warning",
  partial: "info",
  strong: "success",
  "interview-ready": "success",
  "not-applicable": "neutral",
  "needs-verification": "warning",
};

interface QualityStatusBadgeProps {
  status: QualityStatus;
  compact?: boolean;
  className?: string;
}

export function QualityStatusBadge({ status, compact = false, className }: QualityStatusBadgeProps) {
  return (
    <StatusMarker
      className={`${styles.qualityBadge} ${styles[`quality_${status.replace("-", "_")}`]} ${className ?? ""}`}
      data-quality={status}
      aria-label={`Status: ${QUALITY_STATUS_LABEL[status]}`}
      icon={QUALITY_STATUS_ICON[status]}
      label={QUALITY_STATUS_LABEL[status]}
      description={QUALITY_STATUS_DESCRIPTION[status]}
      tone={QUALITY_STATUS_TONE[status]}
      compact={compact}
      title={QUALITY_STATUS_DESCRIPTION[status]}
    />
  );
}

interface BulletReadinessSummaryProps {
  record: CorpusRecord;
  expanded?: boolean;
  onToggle?: () => void;
}

export function BulletReadinessSummaryBar({ record, expanded = false, onToggle }: BulletReadinessSummaryProps) {
  const summary = useMemo(() => summarizeBulletReadiness(record), [record]);
  const total = summary.segments.reduce((sum, segment) => sum + segment.count, 0) || 1;

  return (
    <div className={styles.readinessSummary}>
      <button
        type="button"
        className={styles.readinessSummaryToggle}
        onClick={onToggle}
        aria-expanded={expanded}
        aria-label={`Readiness: ${summary.missingCount} missing, ${summary.weakCount} need detail, ${summary.interviewReadyCount} interview ready`}
      >
        <div className={styles.readinessBar} role="img" aria-hidden="true">
          {summary.segments.map((segment) => (
            <span
              key={segment.status}
              className={`${styles.readinessSegment} ${styles[`quality_${segment.status.replace("-", "_")}`]}`}
              style={{ flexGrow: segment.count }}
              title={`${QUALITY_STATUS_LABEL[segment.status]}: ${segment.count}`}
            />
          ))}
        </div>
        <div className={styles.readinessMeta}>
          <QualityStatusBadge status={summary.overallStatus} compact />
          <span className={styles.readinessCounts}>
            {summary.missingCount > 0 ? `${summary.missingCount} missing` : null}
            {summary.weakCount > 0 ? `${summary.missingCount > 0 ? " · " : ""}${summary.weakCount} need detail` : null}
            {summary.interviewReadyCount > 0 ? ` · ${summary.interviewReadyCount} ready` : null}
          </span>
          <span className={styles.readinessRoast}>{summary.roastResistance}/100</span>
        </div>
      </button>

      {expanded ? (
        <div className={styles.readinessBreakdown} role="region" aria-label="Readiness breakdown">
          <p><strong>Biggest gap:</strong> {summary.topGap}</p>
          <p><strong>Completion:</strong> {summary.completionPercent}% · {total} tracked categories</p>
          <ul className={styles.readinessBreakdownList}>
            {summary.segments.map((segment) => (
              <li key={segment.status}>
                <QualityStatusBadge status={segment.status} compact />
                <span>{segment.count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

type GapSort = "impact" | "severity" | "interview" | "effort" | "status" | "reviewer";

interface BulletGapMapProps {
  record: CorpusRecord;
  onJumpToSection?: (sectionId: string) => void;
  onUpdateField?: (field: keyof CorpusRecord, value: string) => void;
  onMarkNotApplicable?: (categoryId: GapCategoryId) => void;
  onMarkMetricVerified?: () => void;
  onStatusChange?: (categoryId: GapCategoryId, status?: QualityStatus) => void;
  onAttachEvidence?: (categoryId: GapCategoryId, evidence: { name: string; type: string; url: string }) => void;
  onAddGeneratedQuestion?: (question: GeneratedQuestion) => void;
}

export function BulletGapMap({
  record,
  onJumpToSection,
  onUpdateField,
  onMarkNotApplicable,
  onMarkMetricVerified,
  onStatusChange,
  onAttachEvidence,
  onAddGeneratedQuestion,
}: BulletGapMapProps) {
  const gaps = useMemo(() => buildGapMap(record), [record]);
  const generated = useMemo(() => generateMissingQuestions(record), [record]);
  const defaultOpen = gaps.find((gap) => gap.status === "missing" || gap.status === "weak" || gap.status === "needs-verification")?.id;
  const [expanded, setExpanded] = useState<Set<GapCategoryId>>(() => new Set(defaultOpen ? [defaultOpen] : []));
  const [sort, setSort] = useState<GapSort>("impact");
  const [drafts, setDrafts] = useState<Partial<Record<GapCategoryId, string>>>({});
  const [evidenceDrafts, setEvidenceDrafts] = useState<Partial<Record<GapCategoryId, { name: string; type: string; url: string }>>>({});

  const sorted = useMemo(() => {
    const copy = [...gaps];
    if (sort === "severity") return copy.sort((a, b) => statusRank(a.status) - statusRank(b.status));
    if (sort === "interview") return copy.sort((a, b) => impactRank(b.interviewRisk) - impactRank(a.interviewRisk));
    if (sort === "effort") return copy.sort((a, b) => (a.effort === "low" ? -1 : 1));
    if (sort === "status") return copy.sort((a, b) => a.status.localeCompare(b.status));
    if (sort === "reviewer") return copy.sort((a, b) => (a.reviewerPersona ?? "zzz").localeCompare(b.reviewerPersona ?? "zzz"));
    return copy;
  }, [gaps, sort]);

  const toggle = (id: GapCategoryId) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <section className={styles.panel} aria-labelledby="gap-map-heading">
      <div className={styles.panelHeader}>
        <div>
          <h2 id="gap-map-heading">What is missing from this bullet?</h2>
          <p>One high-impact gap opens by default. Expand others only when ready.</p>
        </div>
        <select className={styles.select} value={sort} onChange={(e) => setSort(e.target.value as GapSort)} aria-label="Sort gaps">
          <option value="impact">Resume impact</option>
          <option value="severity">Severity</option>
          <option value="interview">Interview risk</option>
          <option value="effort">Effort</option>
          <option value="reviewer">Reviewer type</option>
          <option value="status">Status</option>
        </select>
      </div>

      <ul className={styles.gapMapList}>
        {sorted.map((gap) => {
          const isOpen = expanded.has(gap.id);
          const section = GAP_CATEGORIES.find((c) => c.id === gap.id)?.sectionId;
          const field = gapCategoryField(gap.id);
          const draftValue = drafts[gap.id] ?? (typeof gap.currentAnswer === "string" ? gap.currentAnswer : "");
          return (
            <li key={gap.id} data-gap-id={gap.id} className={`${styles.gapMapRow} ${styles[`qualityBorder_${gap.status.replace("-", "_")}`]} ${isOpen ? styles.gapMapRowOpen : ""}`}>
              <button type="button" className={styles.gapMapRowHeader} onClick={() => toggle(gap.id)} aria-expanded={isOpen}>
                <span className={styles.gapMapCategory}>{gap.category}</span>
                <QualityStatusBadge status={gap.status} />
                {!isOpen ? <span className={styles.gapMapCollapsedHint}>{gap.missingDetail || QUALITY_STATUS_LABEL[gap.status]}</span> : null}
              </button>
              {isOpen ? (
                <div className={styles.gapMapExpanded}>
                  <p className={styles.gapMapWhy}><strong>Why it matters:</strong> {gap.whyItMatters}</p>
                  <p className={styles.gapMapQuestion}><strong>Question:</strong> {gap.question}</p>
                  {gap.reviewerPersona ? <p className={styles.gapMapReviewer}><strong>Reviewer:</strong> {gap.reviewerPersona}</p> : null}
                  <p className={styles.gapMapAction}><strong>Next action:</strong> {gap.suggestedAction}</p>
                  {gap.status === "weak" || gap.status === "missing" ? (
                    <p className={styles.gapMapPrompt}><strong>Improve:</strong> {gap.suggestedAction}</p>
                  ) : null}
                  <div className={styles.gapMapMeta}>
                    <span>Resume impact: {gap.resumeImpact}</span>
                    <span>Interview risk: {gap.interviewRisk}</span>
                    <span>Effort: {gap.effort}</span>
                  </div>

                  {field && onUpdateField ? (
                    <div className={styles.fieldGroup}>
                      <label className={styles.label} htmlFor={`gap-answer-${gap.id}`}>Answer</label>
                      <textarea
                        id={`gap-answer-${gap.id}`}
                        className={styles.textarea}
                        rows={4}
                        value={draftValue}
                        placeholder="Capture the missing detail with ownership, metric, and tradeoff where relevant."
                        onChange={(event) => setDrafts((current) => ({ ...current, [gap.id]: event.currentTarget.value }))}
                      />
                      <div className={styles.workspaceActions}>
                        <button
                          type="button"
                          className={styles.primaryButton}
                          disabled={!draftValue.trim()}
                          onClick={() => onUpdateField(field, draftValue.trim())}
                        >
                          Save answer
                        </button>
                        {section && onJumpToSection ? (
                          <button type="button" className={styles.textButton} onClick={() => onJumpToSection(section)}>Open full section →</button>
                        ) : null}
                      </div>
                    </div>
                  ) : section && onJumpToSection ? (
                    <button type="button" className={styles.textButton} onClick={() => onJumpToSection(section)}>Edit in section →</button>
                  ) : null}

                  <div className={styles.gapMapControls}>
                    {onStatusChange ? (
                      <label className={styles.fieldGroup} htmlFor={`gap-status-${gap.id}`}>
                        <span className={styles.label}>Status control</span>
                        <select
                          id={`gap-status-${gap.id}`}
                          className={styles.select}
                          value={record.qualityStatusOverrides[gap.id] ?? "automatic"}
                          onChange={(event) => onStatusChange(gap.id, event.currentTarget.value === "automatic" ? undefined : event.currentTarget.value as QualityStatus)}
                        >
                          <option value="automatic">Automatic assessment</option>
                          <option value="missing">Missing</option>
                          <option value="weak">Needs detail</option>
                          <option value="partial">Partial</option>
                          <option value="strong">Strong</option>
                          <option value="interview-ready">Interview ready</option>
                          <option value="needs-verification">Needs verification</option>
                          <option value="not-applicable">Not applicable</option>
                        </select>
                      </label>
                    ) : null}
                    {onMarkNotApplicable ? (
                      <button type="button" className={styles.quietButton} onClick={() => onMarkNotApplicable(gap.id)}>
                        Mark not applicable
                      </button>
                    ) : null}
                    {gap.id === "metric-validation" && onMarkMetricVerified ? (
                      <button type="button" className={styles.quietButton} onClick={onMarkMetricVerified}>
                        Mark metric verified
                      </button>
                    ) : null}
                  </div>

                  {onAttachEvidence ? (() => {
                    const evidenceDraft = evidenceDrafts[gap.id] ?? { name: "", type: "doc", url: "" };
                    return (
                      <div className={styles.gapEvidenceComposer}>
                        <strong>Attach evidence to this gap</strong>
                        <div className={styles.fieldGrid}>
                          <label className={styles.fieldGroup} htmlFor={`gap-evidence-name-${gap.id}`}>
                            <span className={styles.label}>Artifact name</span>
                            <input id={`gap-evidence-name-${gap.id}`} className={styles.field} value={evidenceDraft.name} onChange={(event) => setEvidenceDrafts((current) => ({ ...current, [gap.id]: { ...evidenceDraft, name: event.currentTarget.value } }))} />
                          </label>
                          <label className={styles.fieldGroup} htmlFor={`gap-evidence-url-${gap.id}`}>
                            <span className={styles.label}>URL or path</span>
                            <input id={`gap-evidence-url-${gap.id}`} className={styles.field} value={evidenceDraft.url} onChange={(event) => setEvidenceDrafts((current) => ({ ...current, [gap.id]: { ...evidenceDraft, url: event.currentTarget.value } }))} />
                          </label>
                          <label className={styles.fieldGroup} htmlFor={`gap-evidence-type-${gap.id}`}>
                            <span className={styles.label}>Type</span>
                            <select id={`gap-evidence-type-${gap.id}`} className={styles.select} value={evidenceDraft.type} onChange={(event) => setEvidenceDrafts((current) => ({ ...current, [gap.id]: { ...evidenceDraft, type: event.currentTarget.value } }))}>
                              <option value="doc">Document</option>
                              <option value="rfc">RFC</option>
                              <option value="dashboard">Dashboard</option>
                              <option value="pr">Pull request</option>
                              <option value="screenshot">Screenshot</option>
                            </select>
                          </label>
                        </div>
                        <button
                          type="button"
                          className={styles.quietButton}
                          disabled={!evidenceDraft.name.trim() || !evidenceDraft.url.trim()}
                          onClick={() => {
                            onAttachEvidence(gap.id, evidenceDraft);
                            setEvidenceDrafts((current) => ({ ...current, [gap.id]: { name: "", type: "doc", url: "" } }));
                          }}
                        >
                          Attach to {gap.category.toLowerCase()}
                        </button>
                      </div>
                    );
                  })() : null}

                  {generated.some((question) => question.category === gap.id) ? (
                    <div className={styles.gapFollowUps}>
                      <strong>Likely follow-up questions</strong>
                      {generated.filter((question) => question.category === gap.id).slice(0, 3).map((question) => (
                        <div className={styles.compactRow} key={question.id}>
                          <span className={styles.rowCopy}><span>{question.question}</span><span>{question.reviewerPersona}</span></span>
                          {onAddGeneratedQuestion ? <button type="button" className={styles.textButton} onClick={() => onAddGeneratedQuestion(question)}>Add to question bank</button> : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      {generated.length > 0 ? (
        <div className={styles.gapMapGenerated}>
          <h3>Suggested questions from this bullet</h3>
          <ul>
            {generated.slice(0, 6).map((q) => (
              <li key={q.id}>
                <strong>{q.reviewerPersona}:</strong> {q.question}
                {onAddGeneratedQuestion ? <button type="button" className={styles.textButton} onClick={() => onAddGeneratedQuestion(q)}>Add</button> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

interface BulletHeatmapProps {
  records: CorpusRecord[];
  onSelectCell: (recordId: string, dimension: string) => void;
}

export function BulletHeatmap({ records, onSelectCell }: BulletHeatmapProps) {
  const [compact, setCompact] = useState(false);

  return (
    <section className={styles.panel} aria-labelledby="heatmap-heading">
      <div className={styles.panelHeader}>
        <div>
          <h2 id="heatmap-heading">Resume bullet heatmap</h2>
          <p>Quality across ownership, architecture, evidence, and interview readiness.</p>
        </div>
        <label className={styles.filterChip}>
          <input type="checkbox" checked={compact} onChange={(e) => setCompact(e.target.checked)} />
          Compact mode
        </label>
      </div>

      <div className={styles.heatmapWrap} role="region" aria-label="Bullet quality heatmap">
        <table className={`${styles.heatmapTable} ${compact ? styles.heatmapCompact : ""}`}>
          <thead>
            <tr>
              <th scope="col">Bullet</th>
              {HEATMAP_DIMENSIONS.map((dim) => (
                <th scope="col" key={dim.id}><span className={styles.heatmapColLabel}>{dim.label}</span></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {records.map((record) => (
              <tr key={record.id}>
                <th scope="row" className={styles.heatmapRowLabel}>{record.title}</th>
                {HEATMAP_DIMENSIONS.map((dim) => {
                  const status = dimensionStatus(record, dim.id);
                  return (
                    <td key={dim.id}>
                      <button
                        type="button"
                        className={`${styles.heatmapCell} ${styles[`quality_${status.replace("-", "_")}`]}`}
                        onClick={() => onSelectCell(record.id, dim.id)}
                        aria-label={`${record.title} · ${dim.label}: ${QUALITY_STATUS_LABEL[status]}`}
                        title={`${dim.label}: ${QUALITY_STATUS_LABEL[status]}`}
                      >
                        <span aria-hidden="true">{QUALITY_STATUS_ICON[status]}</span>
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface PriorityQueuePanelProps {
  records: CorpusRecord[];
  onSelect: (item: PriorityItem) => void;
  limit?: number;
}

export function PriorityQueuePanel({ records, onSelect, limit = 5 }: PriorityQueuePanelProps) {
  const items = useMemo(() => rankPriorityItems(records, limit), [records, limit]);
  if (items.length === 0) return null;

  return (
    <section className={styles.panel} aria-labelledby="priority-queue-heading">
      <div className={styles.panelHeader}>
        <div>
          <h2 id="priority-queue-heading">Highest-value questions to answer next</h2>
          <p>Ranked by resume impact and interview risk — only the top {limit} shown.</p>
        </div>
      </div>
      <ol className={styles.priorityList}>
        {items.map((item, index) => (
          <li key={item.id}>
            <button type="button" className={styles.priorityItem} onClick={() => onSelect(item)}>
              <span className={styles.actionNumber} aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
              <span className={styles.rowCopy}>
                <strong>{item.title}</strong>
                <span>{item.recordTitle} · {item.whyItMatters}</span>
                <span className={styles.priorityBenefit}>{item.benefit}</span>
              </span>
              <span className={styles.statusTag}>{item.resumeImpact} impact</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

interface ResearchQueuePanelProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string) => void;
}

const RESEARCH_STATUS_OPTIONS: Array<{ value: ResearchItem["status"]; label: string }> = [
  { value: "open", label: "Open" },
  { value: "found", label: "Found" },
  { value: "verified", label: "Verified" },
  { value: "estimated", label: "Estimated" },
  { value: "unavailable", label: "Unavailable" },
  { value: "not-disclosable", label: "Not safe to disclose" },
  { value: "not-worth", label: "Not worth including" },
];

function loadResearchOverrides(): Record<string, ResearchItem["status"]> {
  try {
    return JSON.parse(window.localStorage.getItem("careeros:corpus:research-status") ?? "{}") as Record<string, ResearchItem["status"]>;
  } catch {
    return {};
  }
}

function loadManualResearchTasks(): ResearchItem[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem("careeros:corpus:research-tasks") ?? "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((value) => {
      if (!value || typeof value !== "object") return [];
      const task = value as Record<string, unknown>;
      if (!task.id || !task.recordId || !task.recordTitle || !task.missingFact) return [];
      return [{
        id: String(task.id),
        recordId: String(task.recordId),
        recordTitle: String(task.recordTitle),
        missingFact: String(task.missingFact),
        whyItMatters: String(task.whyItMatters || "Resolve this gap before relying on the claim."),
        whereToLook: String(task.whereToLook || "Project docs, dashboards, or review notes"),
        suggestedSource: String(task.suggestedSource || "Focus mode task"),
        priority: task.priority === "medium" || task.priority === "low" ? task.priority : "high",
        status: "open" as const,
        notes: task.notes ? String(task.notes) : undefined,
      }];
    });
  } catch {
    return [];
  }
}

export function ResearchQueuePanel({ records, onSelectRecord }: ResearchQueuePanelProps) {
  const baseItems = useMemo(() => buildResearchQueue(records), [records]);
  const [overrides, setOverrides] = useState<Record<string, ResearchItem["status"]>>({});
  const [manualItems, setManualItems] = useState<ResearchItem[]>([]);
  const [statusFilter, setStatusFilter] = useState<ResearchItem["status"] | "all">("open");

  useEffect(() => {
    setOverrides(loadResearchOverrides());
    const refreshManualItems = () => setManualItems(loadManualResearchTasks());
    refreshManualItems();
    window.addEventListener("careeros:corpus:research-updated", refreshManualItems);
    return () => window.removeEventListener("careeros:corpus:research-updated", refreshManualItems);
  }, []);

  const items = [...manualItems, ...baseItems].map((item) => ({
    ...item,
    status: overrides[item.id] ?? item.status,
  }));
  const filtered = items.filter((item) => statusFilter === "all" || item.status === statusFilter);

  const setItemStatus = (id: string, status: ResearchItem["status"]) => {
    setOverrides((current) => {
      const next = { ...current, [id]: status };
      try {
        window.localStorage.setItem("careeros:corpus:research-status", JSON.stringify(next));
      } catch {
        // Queue still updates in-session without storage.
      }
      return next;
    });
  };

  if (items.length === 0) return null;

  return (
    <section className={styles.panel} aria-labelledby="research-queue-heading">
      <div className={styles.panelHeader}>
        <div>
          <h2 id="research-queue-heading">Research queue</h2>
          <p>Facts to find or validate later — linked to specific bullets.</p>
        </div>
        <select className={styles.select} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)} aria-label="Filter research status">
          <option value="all">All</option>
          {RESEARCH_STATUS_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>
      <ul className={styles.researchList}>
        {filtered.slice(0, 12).map((item) => (
          <li key={item.id} className={styles.researchRow}>
            <button type="button" className={styles.researchRowButton} onClick={() => onSelectRecord(item.recordId)}>
              <strong>{item.missingFact}</strong>
              <span>{item.recordTitle} · Look in: {item.whereToLook || item.suggestedSource}</span>
              <span className={styles.researchWhy}>{item.whyItMatters}</span>
            </button>
            <div className={styles.researchControls}>
              <span className={`${styles.statusTag} ${styles[`priority_${item.priority}`]}`}>{item.priority}</span>
              <label className={styles.srOnly} htmlFor={`research-status-${item.id}`}>Status for {item.missingFact}</label>
              <select
                id={`research-status-${item.id}`}
                className={styles.select}
                value={item.status}
                onChange={(event) => setItemStatus(item.id, event.currentTarget.value as ResearchItem["status"])}
              >
                {RESEARCH_STATUS_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface QuestionQualityCardProps {
  question: CorpusQuestionView;
  record: CorpusRecord;
  onEdit?: () => void;
  onAnswerChange?: (value: string) => void;
  onQuestionChange?: (updates: Partial<CorpusQuestionView>) => void;
}

export function QuestionQualityCard({ question, record, onEdit, onAnswerChange, onQuestionChange }: QuestionQualityCardProps) {
  const quality = useMemo(() => evaluateQuestionQuality(question, record), [question, record]);
  const [expanded, setExpanded] = useState(false);

  return (
    <article className={`${styles.questionQualityCard} ${styles[`qualityBorder_${quality.status.replace("-", "_")}`]}`}>
      <button type="button" className={styles.questionQualityHeader} onClick={() => setExpanded((v) => !v)} aria-expanded={expanded}>
        <p className={styles.questionQualityText}>{question.question}</p>
        <div className={styles.questionQualityMeta}>
          <QualityStatusBadge status={quality.status} />
          <span>{question.reviewerPersona}</span>
          <span>{question.difficulty}</span>
        </div>
      </button>
      {question.preparedAnswer && !expanded ? (
        <p className={styles.questionPreview}>{question.preparedAnswer.slice(0, 120)}{question.preparedAnswer.length > 120 ? "…" : ""}</p>
      ) : null}
      {!expanded ? (
        <p className={styles.questionPreview}>{quality.missingElements.length} missing element{quality.missingElements.length === 1 ? "" : "s"} · {question.followUpQuestions.length} follow-up{question.followUpQuestions.length === 1 ? "" : "s"}</p>
      ) : null}
      {expanded ? (
        <div className={styles.questionQualityBody}>
          <div className={styles.questionScoreSummary} aria-label={`Answer quality ${quality.score} out of 100`}>
            <strong>{quality.score}/100 structured quality</strong>
            <span>Score is explained by the ten checks below; writing style alone does not determine it.</span>
          </div>
          {quality.personaNotes ? <p><strong>Reviewer lens:</strong> {quality.personaNotes}</p> : null}
          {quality.strengths.length > 0 ? <p><strong>Strengths:</strong> {quality.strengths.join(" · ")}</p> : null}
          {quality.weaknesses.length > 0 ? <p><strong>Needs work:</strong> {quality.weaknesses.join(" · ")}</p> : null}
          {quality.missingElements.length > 0 ? <p><strong>Missing:</strong> {quality.missingElements.join(" · ")}</p> : null}
          {quality.improvementPrompt ? <p><strong>Next:</strong> {quality.improvementPrompt}</p> : null}
          <div className={styles.answerDimensionGrid} aria-label="Answer quality dimensions">
            {quality.dimensions.map((dimension) => (
              <div key={dimension.id} className={styles.answerDimensionRow}>
                <QualityStatusBadge status={dimension.status} compact />
                <span><strong>{dimension.label}</strong><span>{dimension.reason}</span></span>
              </div>
            ))}
          </div>
          {onAnswerChange ? (
            <div className={styles.fieldGroup}>
              <label className={styles.label} htmlFor={`quality-answer-${question.id}`}>Prepared answer</label>
              <textarea
                id={`quality-answer-${question.id}`}
                className={styles.textarea}
                rows={6}
                value={question.preparedAnswer ?? ""}
                placeholder="Direct answer, ownership, tradeoff, metric, and evidence."
                onChange={(event) => onAnswerChange(event.currentTarget.value)}
              />
            </div>
          ) : onEdit ? (
            <button type="button" className={styles.textButton} onClick={onEdit}>Edit answer</button>
          ) : null}

          {onQuestionChange ? (
            <div className={styles.questionEditorGrid}>
              <label className={styles.fieldGroup} htmlFor={`question-workflow-${question.id}`}>
                <span className={styles.label}>Question state</span>
                <select id={`question-workflow-${question.id}`} className={styles.select} value={question.answerStatus} onChange={(event) => onQuestionChange({ answerStatus: event.currentTarget.value as CorpusQuestionView["answerStatus"] })}>
                  <option value="unanswered">Unanswered</option>
                  <option value="draft">Draft</option>
                  <option value="prepared">Strong / prepared</option>
                  <option value="practiced">Interview ready / practiced</option>
                </select>
              </label>
              <label className={styles.fieldGroup} htmlFor={`question-quality-status-${question.id}`}>
                <span className={styles.label}>Quality exception</span>
                <select id={`question-quality-status-${question.id}`} className={styles.select} value={question.qualityStatus ?? "automatic"} onChange={(event) => onQuestionChange({ qualityStatus: event.currentTarget.value === "automatic" ? undefined : event.currentTarget.value as QualityStatus })}>
                  <option value="automatic">Automatic assessment</option>
                  <option value="needs-verification">Needs verification</option>
                  <option value="not-applicable">Not applicable</option>
                </select>
              </label>
              <label className={styles.fieldGroup} htmlFor={`question-confidence-${question.id}`}>
                <span className={styles.label}>Confidence: {question.confidence}%</span>
                <input id={`question-confidence-${question.id}`} type="range" min={0} max={100} step={5} value={question.confidence} onChange={(event) => onQuestionChange({ confidence: Number(event.currentTarget.value) })} />
              </label>
              <label className={styles.fieldGroup} htmlFor={`question-followups-${question.id}`}>
                <span className={styles.label}>Follow-up questions (one per line)</span>
                <textarea id={`question-followups-${question.id}`} className={styles.textarea} rows={3} value={question.followUpQuestions.join("\n")} onChange={(event) => onQuestionChange({ followUpQuestions: event.currentTarget.value.split("\n").map((value) => value.trim()).filter(Boolean) })} />
              </label>
              <fieldset className={styles.questionLinkFieldset}>
                <legend>Evidence for this answer</legend>
                {record.evidence.length === 0 ? <span className={styles.helper}>Attach evidence to the bullet first.</span> : record.evidence.map((item) => (
                  <label key={item.id} className={styles.checkboxRow}>
                    <input type="checkbox" checked={question.evidenceIds.includes(item.id)} onChange={(event) => onQuestionChange({ evidenceIds: event.currentTarget.checked ? [...question.evidenceIds, item.id] : question.evidenceIds.filter((id) => id !== item.id) })} />
                    <span>{item.name}</span>
                  </label>
                ))}
              </fieldset>
              <fieldset className={styles.questionLinkFieldset}>
                <legend>Metrics referenced by this answer</legend>
                {record.metrics.length === 0 ? <span className={styles.helper}>No metrics are recorded.</span> : record.metrics.map((metric) => (
                  <label key={metric.id} className={styles.checkboxRow}>
                    <input type="checkbox" checked={question.metricIds.includes(metric.id)} onChange={(event) => onQuestionChange({ metricIds: event.currentTarget.checked ? [...question.metricIds, metric.id] : question.metricIds.filter((id) => id !== metric.id) })} />
                    <span>{metric.name}: {metric.value} · {metric.verification.replace("-", " ")}</span>
                  </label>
                ))}
              </fieldset>
              <div className={styles.practiceHistoryBlock}>
                <strong>Practice history</strong>
                {question.practiceHistory.length > 0 ? <ul>{question.practiceHistory.slice(-3).map((entry) => <li key={entry}>{new Date(entry).toLocaleString()}</li>)}</ul> : <p>No practice session recorded.</p>}
                <button type="button" className={styles.quietButton} onClick={() => onQuestionChange({ practiceHistory: [...question.practiceHistory, new Date().toISOString()], answerStatus: "practiced" })}>Record practice</button>
              </div>
              {question.reviewerFeedback.length > 0 ? <div className={styles.answerBlock}><strong>Reviewer feedback</strong><ul>{question.reviewerFeedback.map((feedback) => <li key={feedback}>{feedback}</li>)}</ul></div> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

interface ResumeBulletByRecordProps {
  records: CorpusRecord[];
}

export function QuestionsByBulletPanel({ records, onSelectRecord, onOpenFocus }: {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string, sectionId?: string) => void;
  onOpenFocus?: (recordId: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  return (
    <section className={styles.viewStack} aria-labelledby="by-bullet-heading">
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Interview Preparation</div>
          <h2 id="by-bullet-heading">Questions triggered by my resume</h2>
          <p>Grouped by bullet with unanswered and weak counts visible at a glance.</p>
        </div>
      </header>

      <ul className={styles.byBulletList}>
        {records.filter((r) => r.interviewQuestions.length > 0 || r.currentBullet).map((record) => {
          const generated = generateMissingQuestions(record);
          const allQuestions = [...record.interviewQuestions];
          const unanswered = allQuestions.filter((q) => q.answerStatus === "unanswered").length;
          const weak = allQuestions.filter((q) => evaluateQuestionQuality(q, record).status === "weak").length;
          const ready = allQuestions.filter((q) => evaluateQuestionQuality(q, record).status === "interview-ready" || q.answerStatus === "practiced").length;
          const isOpen = expanded.has(record.id);

          return (
            <li key={record.id} className={styles.byBulletItem}>
              <button
                type="button"
                className={styles.byBulletHeader}
                onClick={() => setExpanded((s) => { const n = new Set(s); if (n.has(record.id)) n.delete(record.id); else n.add(record.id); return n; })}
                aria-expanded={isOpen}
              >
                <strong>{record.title}</strong>
                <span className={styles.byBulletCounts}>
                  {unanswered > 0 ? `${unanswered} unanswered` : null}
                  {weak > 0 ? `${unanswered > 0 ? " · " : ""}${weak} need detail` : null}
                  {ready > 0 ? ` · ${ready} interview ready` : null}
                </span>
              </button>
              {isOpen ? (
                <div className={styles.byBulletBody}>
                  <BulletReadinessSummaryBar record={record} />
                  <div className={styles.byBulletActions}>
                    <button type="button" className={styles.textButton} onClick={() => onSelectRecord(record.id, "interview")}>Open workspace</button>
                    {onOpenFocus ? <button type="button" className={styles.primaryButton} onClick={() => onOpenFocus(record.id)}>Focus mode</button> : null}
                  </div>
                  {["Recruiter", "Hiring manager", "Senior", "Staff", "Principal", "Security", "Reliability", "Devil"].map((personaKey) => {
                    const group = allQuestions.filter((q) => q.reviewerPersona.toLowerCase().includes(personaKey.toLowerCase()));
                    if (group.length === 0) return null;
                    return (
                      <div key={personaKey} className={styles.byBulletPersonaGroup}>
                        <h3 className={styles.gapMapCategory}>{personaKey} questions</h3>
                        {group.map((q) => (
                          <QuestionQualityCard key={q.id} question={q} record={record} onEdit={() => onSelectRecord(record.id, "interview")} />
                        ))}
                      </div>
                    );
                  })}
                  {allQuestions.filter((q) => !["recruiter", "hiring", "senior", "staff", "principal", "security", "reliability", "devil"].some((key) => q.reviewerPersona.toLowerCase().includes(key))).map((q) => (
                    <QuestionQualityCard key={q.id} question={q} record={record} onEdit={() => onSelectRecord(record.id, "interview")} />
                  ))}
                  {generated.slice(0, 4).map((q) => (
                    <div key={q.id} className={styles.generatedQuestion}>
                      <QualityStatusBadge status="missing" compact />
                      <span><strong>{q.reviewerPersona}:</strong> {q.question}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export { summarizeBulletReadiness, evaluateQuestionQuality, evaluateResumeBullet } from "../corpus-quality";
export type { PriorityItem, GapItem, QualityStatus };
