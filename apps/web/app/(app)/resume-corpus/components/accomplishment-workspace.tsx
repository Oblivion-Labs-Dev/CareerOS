"use client";

import { DisclosureSection, ScoreGauge, StatePanel } from "@arsenal/ui";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { CorpusQuestionView, CorpusRecord } from "../corpus-model";
import { gapCategoryField, mapReviewerConcern, summarizeBulletReadiness, type GapCategoryId, type GeneratedQuestion, type QualityStatus } from "../corpus-quality";
import { recordCorpusPerformance } from "../corpus-performance";
import { BulletGapMap, BulletReadinessSummaryBar, QualityStatusBadge, QuestionQualityCard } from "./corpus-quality-ui";
import { CorpusFocusMode } from "./corpus-focus-mode";
import styles from "../resume-corpus.module.css";

type SaveStatus = "saved" | "unsaved" | "saving" | "error";
type SectionId =
  | "overview"
  | "context"
  | "ownership"
  | "challenge"
  | "architecture"
  | "tradeoffs"
  | "failure"
  | "reliability"
  | "security"
  | "scale"
  | "business"
  | "engineering"
  | "leadership"
  | "evidence"
  | "concerns"
  | "interview"
  | "variants"
  | "publishing"
  | "history";

interface SectionDefinition {
  id: SectionId;
  label: string;
  summary: (record: CorpusRecord) => string;
  completion: (record: CorpusRecord) => number;
}

const present = (value: string) => value.trim().length > 0;
const textCompletion = (value: string) => present(value) ? 100 : 0;

const SECTIONS: SectionDefinition[] = [
  { id: "overview", label: "Overview", summary: (record) => `${record.company} · ${record.timePeriod}`, completion: (record) => Math.round(([record.title, record.company, record.role, record.project, record.timePeriod, record.currentBullet].filter(present).length / 6) * 100) },
  { id: "context", label: "Problem and context", summary: (record) => record.summary || "Context needed", completion: (record) => textCompletion(record.summary) },
  { id: "ownership", label: "Personal ownership", summary: (record) => record.ownership || "Ownership needed", completion: (record) => textCompletion(record.ownership) },
  { id: "challenge", label: "Technical challenge", summary: (record) => record.technicalChallenge || "Challenge needed", completion: (record) => textCompletion(record.technicalChallenge) },
  { id: "architecture", label: "Architecture", summary: (record) => record.architectureDecision || "Decision needed", completion: (record) => textCompletion(record.architectureDecision) },
  { id: "tradeoffs", label: "Alternatives and tradeoffs", summary: (record) => record.alternatives || record.tradeoffs || "Alternatives and tradeoffs needed", completion: (record) => Math.round((textCompletion(record.alternatives) + textCompletion(record.tradeoffs)) / 2) },
  { id: "failure", label: "Failure modes", summary: (record) => record.failureModes || "Failure modes needed", completion: (record) => textCompletion(record.failureModes) },
  { id: "reliability", label: "Reliability", summary: (record) => record.reliabilityDetails || "Reliability detail needed", completion: (record) => textCompletion(record.reliabilityDetails) },
  { id: "security", label: "Security", summary: (record) => record.securityConsiderations || "Security applicability not documented", completion: (record) => textCompletion(record.securityConsiderations) },
  { id: "scale", label: "Scale", summary: (record) => record.scaleDetails || record.metrics[0]?.value || "Scale needed", completion: (record) => present(record.scaleDetails) || record.metrics.length > 0 ? 100 : 0 },
  { id: "business", label: "Business impact", summary: (record) => record.businessImpact || "Business impact needed", completion: (record) => textCompletion(record.businessImpact) },
  { id: "engineering", label: "Engineering impact", summary: (record) => record.engineeringImpact || "Engineering impact needed", completion: (record) => textCompletion(record.engineeringImpact) },
  { id: "leadership", label: "Leadership", summary: (record) => record.leadership || record.crossTeamInfluence || record.mentorship || "Leadership signal needed", completion: (record) => Math.round((textCompletion(record.leadership) + textCompletion(record.crossTeamInfluence) + textCompletion(record.mentorship)) / 3) },
  { id: "evidence", label: "Evidence", summary: (record) => `${record.evidence.length} linked item${record.evidence.length === 1 ? "" : "s"}`, completion: (record) => Math.min(record.evidence.length * 50, 100) },
  { id: "concerns", label: "Reviewer concerns", summary: (record) => record.concerns[0]?.concern || "No open concerns", completion: (record) => record.concerns.length === 0 ? 100 : Math.round((record.concerns.filter((concern) => concern.status === "resolved" || concern.status === "answered").length / record.concerns.length) * 100) },
  { id: "interview", label: "Interview questions", summary: (record) => `${record.interviewQuestions.filter((question) => question.answerStatus === "unanswered").length} unanswered`, completion: (record) => record.interviewQuestions.length === 0 ? 0 : Math.round((record.interviewQuestions.filter((question) => question.answerStatus !== "unanswered").length / record.interviewQuestions.length) * 100) },
  { id: "variants", label: "Resume variants", summary: (record) => `${record.resumeVariants.length} version${record.resumeVariants.length === 1 ? "" : "s"}`, completion: (record) => present(record.currentBullet) ? 100 : 0 },
  { id: "publishing", label: "LinkedIn and portfolio", summary: (record) => record.linkedInVersion || record.portfolioVersion || "Publishing versions needed", completion: (record) => [record.linkedInVersion, record.portfolioVersion].filter(present).length * 50 },
  { id: "history", label: "Change history", summary: (record) => record.updatedAt ? `Updated ${new Date(record.updatedAt).toLocaleDateString()}` : "Working draft", completion: () => 100 },
];

const DEFAULT_OPEN: SectionId[] = ["overview", "context", "ownership", "architecture", "business"];

interface AccomplishmentWorkspaceProps {
  record: CorpusRecord;
  previewMode: boolean;
  compact?: boolean;
  onBack: () => void;
  onCommit: (record: CorpusRecord) => Promise<void>;
  onDelete: (recordId: string) => Promise<void>;
}

interface FieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  helper?: string;
  multiline?: boolean;
  rows?: number;
}

function EditableField({ id, label, value, onChange, helper, multiline = false, rows = 4 }: FieldProps) {
  return (
    <div className={styles.fieldGroup}>
      <label className={styles.label} htmlFor={id}>{label}</label>
      {multiline
        ? <textarea id={id} className={styles.textarea} rows={rows} value={value} onChange={(event) => onChange(event.currentTarget.value)} />
        : <input id={id} className={styles.field} value={value} onChange={(event) => onChange(event.currentTarget.value)} />}
      {helper ? <p className={styles.helper}>{helper}</p> : null}
    </div>
  );
}

function signature(record: CorpusRecord): string {
  return JSON.stringify({
    title: record.title, company: record.company, role: record.role, project: record.project, timePeriod: record.timePeriod,
    summary: record.summary, currentBullet: record.currentBullet, ownership: record.ownership,
    technicalChallenge: record.technicalChallenge, architectureDecision: record.architectureDecision, alternatives: record.alternatives, tradeoffs: record.tradeoffs,
    failureModes: record.failureModes, reliabilityDetails: record.reliabilityDetails, securityConsiderations: record.securityConsiderations,
    scaleDetails: record.scaleDetails, businessImpact: record.businessImpact, engineeringImpact: record.engineeringImpact,
    leadership: record.leadership, crossTeamInfluence: record.crossTeamInfluence, mentorship: record.mentorship,
    technologies: record.technologies, domains: record.domains, concepts: record.concepts,
    metrics: record.metrics, evidence: record.evidence, concerns: record.concerns, interviewQuestions: record.interviewQuestions,
    resumeVariants: record.resumeVariants, linkedInVersion: record.linkedInVersion, portfolioVersion: record.portfolioVersion,
    qualityStatusOverrides: record.qualityStatusOverrides,
  });
}

export function AccomplishmentWorkspace({ record, previewMode, compact = false, onBack, onCommit, onDelete }: AccomplishmentWorkspaceProps) {
  const [history, setHistory] = useState<CorpusRecord[]>([record]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [openSections, setOpenSections] = useState<Set<SectionId>>(new Set(DEFAULT_OPEN));
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("saved");
  const [intelligenceOpen, setIntelligenceOpen] = useState(!compact);
  const [focusOpen, setFocusOpen] = useState(false);
  const [readinessOpen, setReadinessOpen] = useState(false);
  const [evidenceDraft, setEvidenceDraft] = useState({ name: "", type: "doc", url: "" });
  const lastCommittedRef = useRef(signature(record));
  const latestSignatureRef = useRef(signature(record));
  const latestSaveRequestRef = useRef(0);
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const draft = history[historyIndex] ?? record;
  const currentSignature = signature(draft);
  latestSignatureRef.current = currentSignature;
  const readiness = useMemo(() => summarizeBulletReadiness(draft), [draft]);
  const overallCompletion = Math.round(SECTIONS.reduce((sum, section) => sum + section.completion(draft), 0) / SECTIONS.length);

  useEffect(() => {
    let restoredRecord = record;
    try {
      const stored = window.localStorage.getItem(`careeros:corpus:draft:${record.id}`);
      if (stored) {
        const candidate = JSON.parse(stored) as CorpusRecord;
        if (candidate.id === record.id) {
          restoredRecord = {
            ...record,
            ...candidate,
            alternatives: candidate.alternatives ?? record.alternatives,
            crossTeamInfluence: candidate.crossTeamInfluence ?? record.crossTeamInfluence,
            mentorship: candidate.mentorship ?? record.mentorship,
            qualityStatusOverrides: candidate.qualityStatusOverrides ?? {},
            evidence: (candidate.evidence ?? record.evidence).map((item) => ({ ...item, relatedGapIds: item.relatedGapIds ?? [] })),
            interviewQuestions: (candidate.interviewQuestions ?? record.interviewQuestions).map((question) => ({
              ...question,
              evidenceIds: question.evidenceIds ?? [],
              metricIds: question.metricIds ?? [],
              followUpQuestions: question.followUpQuestions ?? [],
              reviewerFeedback: question.reviewerFeedback ?? [],
              practiceHistory: question.practiceHistory ?? [],
            })),
          };
        }
      }
    } catch {
      // A corrupt or unavailable local draft must not block the source record.
    }
    setHistory([restoredRecord]);
    setHistoryIndex(0);
    lastCommittedRef.current = signature(record);
    latestSignatureRef.current = signature(restoredRecord);
    setSaveStatus(signature(restoredRecord) === signature(record) ? "saved" : "unsaved");
    try {
      const stored = window.localStorage.getItem(`careeros:corpus:sections:${record.id}`);
      setOpenSections(stored ? new Set(JSON.parse(stored) as SectionId[]) : new Set(DEFAULT_OPEN));
    } catch {
      setOpenSections(new Set(DEFAULT_OPEN));
    }
  }, [record.id]);

  useEffect(() => {
    const sectionId = window.location.hash.replace("#corpus-section-", "") as SectionId;
    if (!SECTIONS.some((section) => section.id === sectionId)) return;
    setOpenSections((current) => new Set([...current, sectionId]));
    window.requestAnimationFrame(() => document.getElementById(`corpus-section-${sectionId}`)?.scrollIntoView({ block: "start" }));
  }, [record.id]);

  const saveDraft = async (nextDraft: CorpusRecord) => {
    const requestId = ++latestSaveRequestRef.current;
    const requestedSignature = signature(nextDraft);
    setSaveStatus("saving");
    const operation = saveQueueRef.current
      .catch(() => undefined)
      .then(() => onCommit(nextDraft));
    saveQueueRef.current = operation.catch(() => undefined);
    try {
      await operation;
      lastCommittedRef.current = requestedSignature;
      if (latestSignatureRef.current === requestedSignature && latestSaveRequestRef.current === requestId) {
        setSaveStatus("saved");
        try {
          window.localStorage.removeItem(`careeros:corpus:draft:${nextDraft.id}`);
        } catch {
          // API persistence succeeded even if local storage is unavailable.
        }
      } else {
        setSaveStatus("unsaved");
      }
    } catch {
      setSaveStatus(latestSaveRequestRef.current === requestId ? "error" : "unsaved");
    }
  };

  useEffect(() => {
    if (currentSignature === lastCommittedRef.current) {
      try {
        window.localStorage.removeItem(`careeros:corpus:draft:${draft.id}`);
      } catch {
        // Local draft cleanup is best effort.
      }
      return;
    }
    try {
      window.localStorage.setItem(`careeros:corpus:draft:${draft.id}`, JSON.stringify(draft));
    } catch {
      // In-memory editing and API sync continue if storage is unavailable.
    }
    setSaveStatus("unsaved");
    const timer = window.setTimeout(() => void saveDraft(draft), 900);
    return () => window.clearTimeout(timer);
  }, [currentSignature]);

  useEffect(() => {
    const protectDraft = (event: BeforeUnloadEvent) => {
      if (currentSignature === lastCommittedRef.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", protectDraft);
    return () => window.removeEventListener("beforeunload", protectDraft);
  }, [currentSignature]);

  const updateDraft = (updater: (current: CorpusRecord) => CorpusRecord) => {
    const startedAt = window.performance.now();
    const next = updater(draft);
    const nextHistory = [...history.slice(0, historyIndex + 1), next].slice(-40);
    setHistory(nextHistory);
    setHistoryIndex(nextHistory.length - 1);
    recordCorpusPerformance("editor-update", window.performance.now() - startedAt, { historySize: nextHistory.length });
  };

  const patch = <K extends keyof CorpusRecord>(key: K, value: CorpusRecord[K]) => updateDraft((current) => ({ ...current, [key]: value }));

  const setSectionOpen = (id: SectionId, open: boolean) => {
    setOpenSections((current) => {
      const next = new Set(current);
      if (open) next.add(id); else next.delete(id);
      try { window.localStorage.setItem(`careeros:corpus:sections:${record.id}`, JSON.stringify([...next])); } catch { /* optional preference */ }
      return next;
    });
  };

  const scrollToSection = (sectionId: string) => {
    const id = sectionId as SectionId;
    if (!SECTIONS.some((section) => section.id === id)) return;
    setSectionOpen(id, true);
    const url = new URL(window.location.href);
    url.hash = `corpus-section-${id}`;
    window.history.replaceState(window.history.state, "", url);
    window.setTimeout(() => document.getElementById(`corpus-section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  };

  const updateQuestionData = (questionId: string, updates: Partial<CorpusQuestionView>) => updateDraft((current) => ({
    ...current,
    interviewQuestions: current.interviewQuestions.map((question) => question.id === questionId ? { ...question, ...updates } : question),
  }));

  const updateQuestion = (questionId: string, answer: string) => updateQuestionData(questionId, {
    preparedAnswer: answer,
    answerStatus: answer.trim() ? "draft" : "unanswered",
  });

  const updateGapStatus = (categoryId: GapCategoryId, status?: QualityStatus) => updateDraft((current) => {
    const nextOverrides = { ...current.qualityStatusOverrides };
    if (status) nextOverrides[categoryId] = status;
    else delete nextOverrides[categoryId];
    return { ...current, qualityStatusOverrides: nextOverrides };
  });

  const attachGapEvidence = (categoryId: GapCategoryId, evidence: { name: string; type: string; url: string }) => updateDraft((current) => ({
    ...current,
    evidence: [...current.evidence, {
      id: `${current.id}-evidence-${Date.now()}`,
      ...evidence,
      relatedGapIds: [categoryId],
    }],
  }));

  const addGeneratedQuestion = (generated: GeneratedQuestion) => updateDraft((current) => {
    if (current.interviewQuestions.some((question) => question.question.trim().toLowerCase() === generated.question.trim().toLowerCase())) return current;
    return {
      ...current,
      interviewQuestions: [...current.interviewQuestions, {
        id: generated.id,
        question: generated.question,
        interviewType: generated.interviewType,
        reviewerPersona: generated.reviewerPersona,
        difficulty: generated.difficulty,
        answerStatus: "unanswered",
        confidence: 0,
        evidenceIds: [],
        metricIds: [],
        followUpQuestions: [],
        reviewerFeedback: [`Generated from ${generated.trigger}.`],
        practiceHistory: [],
      }],
    };
  });

  const saveFocusField = (field: keyof CorpusRecord, value: string) => updateDraft((current) => ({ ...current, [field]: value }));

  const statusLabel = saveStatus === "saving" ? "Saving…" : saveStatus === "unsaved" ? "Unsaved changes" : saveStatus === "error" ? "Save failed" : previewMode ? "Saved in preview" : "All changes saved";

  const section = (id: SectionId, children: ReactNode) => {
    const definition = SECTIONS.find((candidate) => candidate.id === id)!;
    const completion = definition.completion(draft);
    return (
      <DisclosureSection
        id={`corpus-section-${id}`}
        key={id}
        title={definition.label}
        summary={definition.summary(draft)}
        meta={`${completion}% complete`}
        open={openSections.has(id)}
        onOpenChange={(open) => setSectionOpen(id, open)}
        className={styles.disclosure}
        headingLevel={2}
      >
        {children as never}
      </DisclosureSection>
    );
  };

  return (
    <div className={`${styles.viewStack} ${compact ? styles.compactWorkspace : ""}`}>
      <div className={styles.workspaceHeader}>
        <div className={styles.workspaceTitle}>
          <button type="button" className={styles.textButton} onClick={onBack}>{compact ? "← Close panel" : "← Back to explorer"}</button>
          <h1>{draft.title}</h1>
          <p>{draft.company} · {draft.role} · {draft.timePeriod}</p>
        </div>
        <div className={styles.workspaceActions}>
          <span className={styles.saveState} aria-live="polite"><span className={styles.saveDot} aria-hidden="true" />{statusLabel}</span>
          <button type="button" className={styles.quietButton} onClick={() => setHistoryIndex((index) => Math.max(0, index - 1))} disabled={historyIndex === 0}>Undo</button>
          <button type="button" className={styles.quietButton} onClick={() => setHistoryIndex((index) => Math.min(history.length - 1, index + 1))} disabled={historyIndex >= history.length - 1}>Redo</button>
          {!compact ? <button type="button" className={styles.quietButton} onClick={() => setFocusOpen(true)}>Focus mode</button> : null}
          {!compact ? <button type="button" className={styles.quietButton} onClick={() => setIntelligenceOpen((open) => !open)}>{intelligenceOpen ? "Hide intelligence" : "Show intelligence"}</button> : null}
          <button type="button" className={styles.primaryButton} onClick={() => void saveDraft(draft)} disabled={saveStatus === "saving"}>Save now</button>
        </div>
      </div>

      {saveStatus === "error" ? <div className={styles.saveBanner} role="alert"><span>Your draft is safe locally, but the last sync failed.</span><button type="button" className={styles.quietButton} onClick={() => void saveDraft(draft)}>Retry</button></div> : null}

      <BulletReadinessSummaryBar record={draft} expanded={readinessOpen} onToggle={() => setReadinessOpen((open) => !open)} />
      <BulletGapMap
        record={draft}
        onJumpToSection={scrollToSection}
        onUpdateField={(field, value) => patch(field, value as never)}
        onMarkNotApplicable={(categoryId) => updateGapStatus(categoryId, "not-applicable")}
        onMarkMetricVerified={() => updateDraft((current) => ({ ...current, metrics: current.metrics.map((metric) => ({ ...metric, verification: "verified" })) }))}
        onStatusChange={updateGapStatus}
        onAttachEvidence={attachGapEvidence}
        onAddGeneratedQuestion={addGeneratedQuestion}
      />

      <div className={`${styles.editorGrid} ${compact || !intelligenceOpen ? styles.editorGridNoIntel : ""} ${compact ? styles.editorGridCompact : ""}`}>
        {!compact ? (
          <nav className={styles.editorOutline} aria-label="Accomplishment sections">
            <div className={styles.outlineHeader}><strong>Outline</strong><span className={styles.navCount}>{overallCompletion}%</span></div>
            {SECTIONS.map((definition) => (
              <button type="button" className={styles.outlineLink} key={definition.id} onClick={() => scrollToSection(definition.id)}>
                <span>{definition.label}</span><span>{definition.completion(draft)}%</span>
              </button>
            ))}
            <div className={styles.workspaceActions}>
              <button type="button" className={styles.textButton} onClick={() => SECTIONS.forEach((definition) => setSectionOpen(definition.id, true))}>Expand all</button>
              <button type="button" className={styles.textButton} onClick={() => setOpenSections(new Set())}>Collapse all</button>
            </div>
          </nav>
        ) : null}

        <div className={styles.editorContent}>
          {section("overview", <div className={styles.formStack}>
            <EditableField id="record-title" label="Story title" value={draft.title} onChange={(value) => patch("title", value)} helper="A short reusable label for this story." />
            <div className={styles.fieldGrid}>
              <EditableField id="record-company" label="Company or organization" value={draft.company} onChange={(value) => patch("company", value)} />
              <EditableField id="record-role" label="Role" value={draft.role} onChange={(value) => patch("role", value)} />
              <EditableField id="record-project" label="Project" value={draft.project} onChange={(value) => patch("project", value)} />
              <EditableField id="record-period" label="Time period" value={draft.timePeriod} onChange={(value) => patch("timePeriod", value)} />
            </div>
            <EditableField id="record-bullet" label="Current resume bullet" value={draft.currentBullet} onChange={(value) => patch("currentBullet", value)} multiline rows={4} helper={`${draft.currentBullet.length} characters · keep one clear outcome and defensible proof point.`} />
          </div>)}
          {section("context", <EditableField id="record-context" label="Problem and context" value={draft.summary} onChange={(value) => patch("summary", value)} multiline helper="What was broken, constrained, risky, expensive, or newly possible?" />)}
          {section("ownership", <EditableField id="record-ownership" label="What I personally owned" value={draft.ownership} onChange={(value) => patch("ownership", value)} multiline helper="Separate your decisions and execution from the team’s work." />)}
          {section("challenge", <EditableField id="record-challenge" label="Technical challenge" value={draft.technicalChallenge} onChange={(value) => patch("technicalChallenge", value)} multiline />)}
          {section("architecture", <EditableField id="record-architecture" label="Architecture decision" value={draft.architectureDecision} onChange={(value) => patch("architectureDecision", value)} multiline helper="What did you decide, and which principle drove the choice?" />)}
          {section("tradeoffs", <div className={styles.formStack}>
            <EditableField id="record-alternatives" label="Alternatives considered" value={draft.alternatives} onChange={(value) => patch("alternatives", value)} multiline helper="Name the credible approaches you rejected." />
            <EditableField id="record-tradeoffs" label="Tradeoffs accepted" value={draft.tradeoffs} onChange={(value) => patch("tradeoffs", value)} multiline helper="Explain the cost, complexity, or limitation you accepted." />
          </div>)}
          {section("failure", <EditableField id="record-failure" label="Failure modes and recovery" value={draft.failureModes} onChange={(value) => patch("failureModes", value)} multiline />)}
          {section("reliability", <EditableField id="record-reliability" label="Reliability and operability" value={draft.reliabilityDetails} onChange={(value) => patch("reliabilityDetails", value)} multiline />)}
          {section("security", <EditableField id="record-security" label="Security and privacy considerations" value={draft.securityConsiderations} onChange={(value) => patch("securityConsiderations", value)} multiline helper="State explicit controls or explain why security was not material." />)}
          {section("scale", <div className={styles.formStack}>
            <EditableField id="record-scale" label="Scale and performance" value={draft.scaleDetails} onChange={(value) => patch("scaleDetails", value)} multiline />
            {draft.metrics.map((metric, index) => <div className={styles.metricEditorRow} key={metric.id}>
              <div className={styles.fieldGrid}>
                <EditableField id={`metric-name-${metric.id}`} label="Metric" value={metric.name} onChange={(value) => updateDraft((current) => ({ ...current, metrics: current.metrics.map((item, itemIndex) => itemIndex === index ? { ...item, name: value } : item) }))} />
                <EditableField id={`metric-value-${metric.id}`} label="Value" value={metric.value} onChange={(value) => updateDraft((current) => ({ ...current, metrics: current.metrics.map((item, itemIndex) => itemIndex === index ? { ...item, value } : item) }))} />
                <EditableField id={`metric-source-${metric.id}`} label="Evidence source" value={metric.source ?? ""} onChange={(value) => updateDraft((current) => ({ ...current, metrics: current.metrics.map((item, itemIndex) => itemIndex === index ? { ...item, source: value } : item) }))} />
              </div>
              <span className={styles.metricValue}>{metric.value || "Value needed"}</span>
              <QualityStatusBadge status={metric.verification === "verified" ? "strong" : "needs-verification"} />
              <button type="button" className={styles.quietButton} onClick={() => updateDraft((current) => ({ ...current, metrics: current.metrics.map((item, itemIndex) => itemIndex === index ? { ...item, verification: item.verification === "verified" ? "needs-evidence" : "verified" } : item) }))}>
                {metric.verification === "verified" ? "Require verification" : "Mark verified"}
              </button>
            </div>)}
            <button type="button" className={styles.quietButton} onClick={() => updateDraft((current) => ({ ...current, metrics: [...current.metrics, { id: `metric-${Date.now()}`, name: "", value: "", confidence: "medium", verification: "unverified", evidenceIds: [] }] }))}>+ Add metric</button>
          </div>)}
          {section("business", <EditableField id="record-business" label="Business and customer impact" value={draft.businessImpact} onChange={(value) => patch("businessImpact", value)} multiline />)}
          {section("engineering", <EditableField id="record-engineering" label="Engineering and operational impact" value={draft.engineeringImpact} onChange={(value) => patch("engineeringImpact", value)} multiline />)}
          {section("leadership", <div className={styles.formStack}>
            <EditableField id="record-leadership" label="Leadership" value={draft.leadership} onChange={(value) => patch("leadership", value)} multiline />
            <EditableField id="record-cross-team" label="Cross-team influence" value={draft.crossTeamInfluence} onChange={(value) => patch("crossTeamInfluence", value)} multiline />
            <EditableField id="record-mentorship" label="Mentorship" value={draft.mentorship} onChange={(value) => patch("mentorship", value)} multiline />
            <EditableField id="record-technologies" label="Technologies (comma-separated)" value={draft.technologies.join(", ")} onChange={(value) => patch("technologies", value.split(",").map((item) => item.trim()).filter(Boolean))} />
          </div>)}
          {section("evidence", <div className={styles.formStack}>
            {draft.evidence.length ? <div className={styles.evidenceList}>{draft.evidence.map((item, index) => <div className={styles.evidenceRow} key={item.id}><span className={styles.rowCopy}><strong>{item.name}</strong><span>{item.type}{item.relatedGapIds.length > 0 ? ` · Supports ${item.relatedGapIds.join(", ")}` : " · General evidence"}</span></span><a className={styles.textButton} href={item.url} target="_blank" rel="noreferrer">Open</a><button type="button" className={styles.quietButton} onClick={() => updateDraft((current) => ({ ...current, evidence: current.evidence.filter((_, itemIndex) => itemIndex !== index) }))}>Remove</button></div>)}</div> : <StatePanel kind="empty" size="compact" title="No evidence attached" description="Link a safe RFC, document, dashboard, review, or public artifact." />}
            <div className={styles.fieldGrid}>
              <EditableField id="evidence-name" label="Artifact name" value={evidenceDraft.name} onChange={(value) => setEvidenceDraft((current) => ({ ...current, name: value }))} />
              <EditableField id="evidence-url" label="URL or path" value={evidenceDraft.url} onChange={(value) => setEvidenceDraft((current) => ({ ...current, url: value }))} />
              <div className={styles.fieldGroup}>
                <label className={styles.label} htmlFor="evidence-type">Artifact type</label>
                <select id="evidence-type" className={styles.field} value={evidenceDraft.type} onChange={(event) => setEvidenceDraft((current) => ({ ...current, type: event.currentTarget.value }))}>
                  <option value="doc">Document</option>
                  <option value="rfc">RFC</option>
                  <option value="pr">Pull request</option>
                  <option value="dashboard">Dashboard</option>
                  <option value="screenshot">Screenshot</option>
                </select>
              </div>
            </div>
            <button type="button" className={styles.primaryButton} disabled={!evidenceDraft.name.trim() || !evidenceDraft.url.trim()} onClick={() => { updateDraft((current) => ({ ...current, evidence: [...current.evidence, { id: `${current.id}-evidence-${Date.now()}`, ...evidenceDraft, relatedGapIds: [] }] })); setEvidenceDraft({ name: "", type: "doc", url: "" }); }}>Attach evidence</button>
          </div>)}
          {section("concerns", draft.concerns.length ? <div className={styles.concernList}>{draft.concerns.map((concern) => {
            const mapped = mapReviewerConcern(draft, concern);
            return <div className={styles.reviewConcernDetail} key={concern.id}>
              <div className={styles.concernRow}><span className={styles.actionNumber}>{concern.severity.slice(0, 1).toUpperCase()}</span><span className={styles.rowCopy}><strong>{concern.concern}</strong><span>{concern.reviewer} · {concern.category} · {concern.severity} severity</span></span><QualityStatusBadge status={mapped.resolutionStatus} /></div>
              <p><strong>Why it matters:</strong> {mapped.whyItMatters}</p>
              {mapped.question ? <p><strong>Question to answer:</strong> {mapped.question}</p> : null}
              {mapped.response ? <p><strong>Existing answer:</strong> {mapped.response}</p> : null}
              <p><strong>Evidence:</strong> {draft.evidence.filter((item) => item.relatedGapIds.some((gapId) => mapped.question?.toLowerCase().includes(gapId.replace("-", " ")))).map((item) => item.name).join(", ") || "No concern-specific evidence linked."}</p>
              <label className={styles.fieldGroup} htmlFor={`concern-status-${concern.id}`}><span className={styles.label}>Resolution status</span><select id={`concern-status-${concern.id}`} className={styles.select} value={concern.status} onChange={(event) => updateDraft((current) => ({ ...current, concerns: current.concerns.map((item) => item.id === concern.id ? { ...item, status: event.currentTarget.value as typeof item.status } : item) }))}><option value="unanswered">Unanswered</option><option value="investigating">Investigating</option><option value="answered">Answered</option><option value="resolved">Resolved</option><option value="not-applicable">Not applicable</option><option value="intentionally-omitted">Intentionally omitted</option></select></label>
            </div>;
          })}</div> : <StatePanel kind="empty" size="compact" title="No reviewer concerns" description="Re-run review after material edits or a new target role." />)}
          {section("interview", draft.interviewQuestions.length ? <div className={styles.questionList}>{draft.interviewQuestions.map((question) => <QuestionQualityCard key={question.id} question={question} record={draft} onAnswerChange={(value) => updateQuestion(question.id, value)} onQuestionChange={(updates) => updateQuestionData(question.id, updates)} />)}</div> : <StatePanel kind="empty" size="compact" title="No interview questions" description="Add reviewer prompts that test decisions, failures, ownership, and evidence." />)}
          {section("variants", <div className={styles.formStack}><EditableField id="variant-current" label="Current resume bullet" value={draft.currentBullet} onChange={(value) => patch("currentBullet", value)} multiline rows={5} />{draft.resumeVariants.filter((variant) => variant.content !== draft.currentBullet).map((variant) => <div className={styles.panel} key={variant.id}><div className={styles.panelHeader}><h3>{variant.name}</h3><span className={styles.statusTag}>{variant.status}</span></div><p>{variant.content}</p></div>)}</div>)}
          {section("publishing", <div className={styles.formStack}><EditableField id="variant-linkedin" label="LinkedIn version" value={draft.linkedInVersion} onChange={(value) => patch("linkedInVersion", value)} multiline rows={5} /><EditableField id="variant-portfolio" label="Portfolio version" value={draft.portfolioVersion} onChange={(value) => patch("portfolioVersion", value)} multiline rows={7} /></div>)}
          {section("history", <div className={styles.recordList}><div className={styles.recordRow}><span className={styles.actionNumber}>01</span><span className={styles.rowCopy}><strong>Current working version</strong><span>{statusLabel} · {Math.max(history.length - 1, 0)} local edit state{history.length - 1 === 1 ? "" : "s"}</span></span></div>{draft.updatedAt ? <div className={styles.recordRow}><span className={styles.actionNumber}>02</span><span className={styles.rowCopy}><strong>Last persisted update</strong><span>{new Date(draft.updatedAt).toLocaleString()}</span></span></div> : null}<button type="button" className={styles.dangerButton} onClick={() => { if (window.confirm(`Delete “${draft.title}”? This cannot be undone.`)) void onDelete(draft.id); }}>Delete accomplishment</button></div>)}
        </div>

        {!compact && intelligenceOpen ? <aside className={styles.intelligencePanel} aria-label="Contextual intelligence">
          <div className={styles.intelligenceHeader}><strong>Contextual intelligence</strong><button type="button" className={styles.iconButton} onClick={() => setIntelligenceOpen(false)} aria-label="Close intelligence panel">×</button></div>
          <div className={styles.intelScoreGrid}><div className={styles.intelScore}><span>Complete</span><strong>{readiness.completionPercent}%</strong></div><div className={styles.intelScore}><span>Roast resistance</span><strong>{readiness.roastResistance}</strong></div><div className={styles.intelScore}><span>Missing</span><strong>{readiness.missingCount}</strong></div><div className={styles.intelScore}><span>Unanswered</span><strong>{draft.interviewQuestions.filter((question) => question.answerStatus === "unanswered").length}</strong></div></div>
          <div className={styles.matchScore}><ScoreGauge value={readiness.roastResistance} label="Reviewer resilience" description="Recomputed from this record’s current content" size="sm" tone={readiness.roastResistance >= 80 ? "success" : "accent"} /></div>
          <div className={styles.intelBlock}><span>Biggest gap</span><p>{readiness.topGap}</p></div>
          <div className={styles.intelBlock}><span>Best metric</span><p>{draft.metrics[0] ? `${draft.metrics[0].name}: ${draft.metrics[0].value} · ${draft.metrics[0].verification.replace("-", " ")}` : "This story still needs a quantified outcome."}</p></div>
          <div className={styles.intelBlock}><span>Recommended next move</span><p>{draft.nextImprovement}</p></div>
          <div className={styles.intelBlock}><span>Coverage</span><p>{draft.metrics.length} metrics · {draft.evidence.length} evidence · {draft.concerns.length} concerns</p></div>
        </aside> : null}
      </div>

      <CorpusFocusMode
        open={focusOpen}
        record={draft}
        onClose={() => setFocusOpen(false)}
        onSaveAnswer={updateQuestion}
        onSaveField={saveFocusField}
        onMarkNotApplicable={(gapId) => updateGapStatus(gapId as GapCategoryId, "not-applicable")}
        onAttachEvidence={attachGapEvidence}
      />
    </div>
  );
}
