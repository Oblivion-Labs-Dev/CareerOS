"use client";

import { useEffect, useState } from "react";
import type { CorpusProfile, CorpusRecord } from "../corpus-model";
import { CorpusEvidenceVault } from "./corpus-evidence-vault";
import { CorpusInterviewPrep } from "./corpus-interview-prep";
import { CorpusJobMatch } from "./corpus-job-match";
import { CorpusKnowledgeGraph } from "./corpus-knowledge-graph";
import { CorpusMetricsDashboard } from "./corpus-metrics-dashboard";
import { CorpusResumeBuilder } from "./corpus-resume-builder";
import { CorpusReviewCenter } from "./corpus-review-center";
import { CorpusSettings } from "./corpus-settings";
import { CorpusSkillsMap } from "./corpus-skills-map";
import { CorpusTemplates } from "./corpus-templates";

export interface ResumeGenerateRequest {
  targetCompany: string;
  targetRole: string;
  jobDescription: string;
  experienceLevel: string;
  tone: string;
  maxPages: number;
  targetAtsScore: number;
  selectedIds: string[];
}

export interface ResumeGenerateResult {
  targetRoleMatched: string;
  atsMatchScore: number;
  overallCritique: string;
  skillsList: string[];
  provenance: "selected-records" | "generated-draft";
  warnings?: string[];
  resumeBullets: Array<{
    id: string;
    company: string;
    role: string;
    project: string;
    optimizedBullet: string;
  }>;
}

interface RecordViewProps {
  records: CorpusRecord[];
  onSelect: (record: CorpusRecord, sectionId?: string) => void;
}

function recordSelector(records: CorpusRecord[], onSelect: (record: CorpusRecord, sectionId?: string) => void) {
  return (recordId: string, sectionId?: string) => {
    const record = records.find((candidate) => candidate.id === recordId);
    if (record) onSelect(record, sectionId);
  };
}

export function JobMatchView({ records, onSelect }: RecordViewProps) {
  return <CorpusJobMatch records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function InterviewView({ records, onSelect }: RecordViewProps) {
  return <CorpusInterviewPrep records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function MetricsView({ records, onSelect }: RecordViewProps) {
  return <CorpusMetricsDashboard records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function SkillsView({ records, onSelect }: RecordViewProps) {
  return <CorpusSkillsMap records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function KnowledgeGraphView({ records, onSelect }: RecordViewProps) {
  return <CorpusKnowledgeGraph records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function EvidenceView({ records, onSelect }: RecordViewProps) {
  return <CorpusEvidenceVault records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function ReviewCenterView({ records, onSelect }: RecordViewProps) {
  return <CorpusReviewCenter records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

interface ResumeBuilderViewProps {
  records: CorpusRecord[];
  profile: CorpusProfile;
  onGenerate: (request: ResumeGenerateRequest) => Promise<ResumeGenerateResult>;
  onSelect: (record: CorpusRecord, sectionId?: string) => void;
  onCreate: () => void;
}

export function ResumeBuilderView({ records, profile, onGenerate, onSelect, onCreate }: ResumeBuilderViewProps) {
  const [inputs, setInputs] = useState({
    targetCompany: "",
    targetRole: profile.targetRole === "Target role not set" ? "" : profile.targetRole,
    jobDescription: "",
    experienceLevel: "Staff",
    tone: "professional",
    maxPages: 1,
    selectedIds: records.filter((record) => record.readiness === "ready").slice(0, 4).map((record) => record.id),
  });
  const [generated, setGenerated] = useState<{
    content?: string;
    warnings?: string[];
    provenance?: ResumeGenerateResult["provenance"];
  } | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const stored = window.sessionStorage.getItem("careeros:corpus:template-pages");
      if (stored) {
        const pages = Number(stored);
        if (pages >= 1 && pages <= 3) setInputs((current) => ({ ...current, maxPages: pages }));
      }
    } catch {
      // Default length remains valid without storage.
    }
  }, []);

  const generate = async () => {
    if (!inputs.targetRole || inputs.selectedIds.length === 0) return;
    setGenerating(true);
    setGenerationError(null);
    try {
      const result = await onGenerate({ ...inputs, targetAtsScore: 85 });
      const selected = records.filter((record) => inputs.selectedIds.includes(record.id));
      const warnings = [
        ...(result.warnings ?? []),
        ...selected.flatMap((record) => record.metrics.filter((metric) => metric.verification !== "verified").map((metric) => `${record.title}: “${metric.value}” is ${metric.verification.replace("-", " ")}.`)),
        ...selected.filter((record) => record.currentBullet.length > 220).map((record) => `${record.title}: the bullet may be too long for a one-page resume.`),
      ];
      setGenerated({
        content: result.resumeBullets.map((item) => item.optimizedBullet).join("\n"),
        warnings,
        provenance: result.provenance,
      });
    } catch {
      setGenerated(null);
      setGenerationError("Generation is unavailable. No synthetic resume was returned; your selected source bullets remain unchanged.");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <CorpusResumeBuilder
      records={records}
      generatorInputs={inputs}
      generatedResume={generated}
      generationError={generationError}
      generating={generating}
      onInputsChange={setInputs}
      onGenerate={() => void generate()}
      onSelectRecord={recordSelector(records, onSelect)}
      onCreate={onCreate}
    />
  );
}

export function TemplatesView({
  records: _records,
  onUseTemplate,
}: {
  records: CorpusRecord[];
  onUseTemplate?: (templateId: string, maxPages: number) => void;
}) {
  return <CorpusTemplates onUseTemplate={onUseTemplate} />;
}

interface SettingsViewProps {
  profile: CorpusProfile;
  previewMode: boolean;
  onProfileChange: (profile: CorpusProfile) => void;
  onSave: (profile: CorpusProfile) => Promise<void>;
}

export function SettingsView({ profile, previewMode, onProfileChange, onSave }: SettingsViewProps) {
  return (
    <CorpusSettings
      profile={profile}
      previewMode={previewMode}
      onProfileChange={onProfileChange}
      onSave={onSave}
    />
  );
}
