"use client";

import type { CorpusProfile, CorpusRecord } from "../corpus-model";
import { CorpusEvidenceVault } from "./corpus-evidence-vault";
import { CorpusInterviewPrep } from "./corpus-interview-prep";
import { CorpusMetricsDashboard } from "./corpus-metrics-dashboard";
import { CorpusSettings } from "./corpus-settings";

interface RecordViewProps {
  records: CorpusRecord[];
  onSelect: (record: CorpusRecord, sectionId?: string) => void;
}

function recordSelector(records: CorpusRecord[], onSelect: RecordViewProps["onSelect"]) {
  return (recordId: string, sectionId?: string) => {
    const record = records.find((candidate) => candidate.id === recordId);
    if (record) onSelect(record, sectionId);
  };
}

export function InterviewView({ records, onSelect }: RecordViewProps) {
  return <CorpusInterviewPrep records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function MetricsView({ records, onSelect }: RecordViewProps) {
  return <CorpusMetricsDashboard records={records} onSelectRecord={recordSelector(records, onSelect)} />;
}

export function EvidenceView({ records, onSelect }: RecordViewProps) {
  return <CorpusEvidenceVault records={records} onSelectRecord={recordSelector(records, onSelect)} />;
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
