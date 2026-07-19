"use client";

import { StatePanel } from "@arsenal/ui";
import { useMemo, useState } from "react";
import { CorpusEmptyState, FilterChip, SkillDepthIndicator, type SkillDepth, type SkillDepthData } from "@career-os/ui/corpus";
import type { CorpusRecord } from "../corpus-model";
import styles from "../resume-corpus.module.css";

const SKILL_GROUPS = [
  "Languages",
  "Cloud",
  "Distributed systems",
  "AI infrastructure",
  "Machine learning",
  "Security",
  "Platform engineering",
  "Developer productivity",
  "Messaging",
  "Reliability",
  "Databases",
  "Observability",
  "Leadership",
  "Domain expertise",
] as const;

function inferGroup(skill: string): string {
  const lower = skill.toLowerCase();
  if (["go", "python", "typescript", "java", "rust", "c++"].some((lang) => lower.includes(lang))) return "Languages";
  if (["aws", "gcp", "azure", "kubernetes", "terraform"].some((cloud) => lower.includes(cloud))) return "Cloud";
  if (["postgres", "dynamodb", "mysql", "redis"].some((db) => lower.includes(db))) return "Databases";
  if (["kafka", "pulsar", "rabbitmq", "nats", "event", "stream"].some((messaging) => lower.includes(messaging))) return "Messaging";
  if (["opentelemetry", "prometheus", "grafana", "datadog"].some((obs) => lower.includes(obs))) return "Observability";
  if (["argo", "github actions", "buildkite", "jenkins", "ci/cd"].some((tool) => lower.includes(tool))) return "Developer productivity";
  if (lower.includes("security") || lower.includes("auth")) return "Security";
  if (["pytorch", "tensorflow", "scikit", "machine learning", "llm"].some((tool) => lower.includes(tool))) return "Machine learning";
  if (lower.includes("ray") || lower.includes("model") || lower.includes("gpu")) return "AI infrastructure";
  if (lower.includes("lead") || lower.includes("mentor")) return "Leadership";
  if (lower.includes("distributed") || lower.includes("event") || lower.includes("stream")) return "Distributed systems";
  if (lower.includes("sre") || lower.includes("reliab")) return "Reliability";
  return "Platform engineering";
}

function inferDepth(recordCount: number, evidenceCount: number, hasLeadership: boolean): SkillDepth {
  if (hasLeadership && recordCount >= 3 && evidenceCount >= 3) return "leadership";
  if (recordCount >= 3 && evidenceCount >= 3) return "deep";
  if (recordCount >= 2 && evidenceCount >= 2) return "production";
  if (recordCount >= 1 && evidenceCount >= 1) return "working";
  return "exposure";
}

function evidenceForSkill(record: CorpusRecord, skill: string): number {
  const normalizedSkill = skill.toLocaleLowerCase();
  return record.evidence.filter((item) =>
    `${item.name} ${item.type}`.toLocaleLowerCase().includes(normalizedSkill),
  ).length;
}

interface CorpusSkillsMapProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string) => void;
}

export function CorpusSkillsMap({ records, onSelectRecord }: CorpusSkillsMapProps) {
  const [activeGroup, setActiveGroup] = useState<string>("all");

  const skills = useMemo(() => {
    const map = new Map<string, SkillDepthData & { recordIds: string[] }>();
    records.forEach((record) => {
      record.technologies.forEach((skill) => {
        const existing = map.get(skill) ?? {
          name: skill,
          depth: "exposure" as SkillDepth,
          evidenceCount: 0,
          accomplishmentCount: 0,
          group: inferGroup(skill),
          recordIds: [],
        };
        existing.accomplishmentCount += 1;
        existing.evidenceCount += evidenceForSkill(record, skill);
        existing.recordIds.push(record.id);
        existing.depth = inferDepth(existing.accomplishmentCount, existing.evidenceCount, Boolean(record.leadership));
        existing.interviewConfidence = Math.round(
          record.interviewQuestions.filter((question) => question.answerStatus !== "unanswered").length /
            Math.max(record.interviewQuestions.length, 1) * 100,
        );
        map.set(skill, existing);
      });
    });
    return [...map.values()].sort((left, right) => right.accomplishmentCount - left.accomplishmentCount);
  }, [records]);

  const filtered = skills.filter((skill) => activeGroup === "all" || skill.group === activeGroup);
  const verified = filtered.filter((skill) => skill.evidenceCount > 0);
  const unverified = filtered.filter((skill) => skill.evidenceCount === 0);

  if (records.length === 0) {
    return (
      <CorpusEmptyState
        title="No skills mapped yet"
        description="Skills are derived from accomplishment technologies with evidence — never promoted without proof."
      />
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Skills Intelligence</div>
          <h1>Evidence-backed skill map</h1>
          <p>Depth is never promoted from a general project score. It advances only when evidence explicitly names the skill.</p>
        </div>
      </header>

      <div className={styles.toolbar}>
        <div className={styles.toolbarGroup}>
          <FilterChip label="All groups" active={activeGroup === "all"} onClick={() => setActiveGroup("all")} count={skills.length} />
          {SKILL_GROUPS.map((group) => {
            const count = skills.filter((skill) => skill.group === group).length;
            if (count === 0) return null;
            return (
              <FilterChip
                key={group}
                label={group}
                active={activeGroup === group}
                count={count}
                onClick={() => setActiveGroup(group)}
              />
            );
          })}
        </div>
      </div>

      {verified.length > 0 ? <div className={styles.skillsGrid}>
        {verified.map((skill) => (
          <SkillDepthIndicator
            key={skill.name}
            skill={skill}
            onClick={() => onSelectRecord(skill.recordIds[0])}
          />
        ))}
      </div> : <StatePanel kind="empty" size="compact" title="No verified skills in this view" description="Link an artifact that explicitly names a technology before CareerOS assigns a skill-depth level." />}

      {unverified.length > 0 ? (
        <section className={styles.panel} aria-labelledby="unverified-skill-title">
          <div className={styles.panelHeader}>
            <div>
              <h2 id="unverified-skill-title">Unverified technology mentions</h2>
              <p>These tags remain inventory only. They do not contribute to depth until an attached artifact names the skill.</p>
            </div>
          </div>
          <div className={styles.techList}>
            {unverified.map((skill) => (
              <button type="button" className={styles.techTag} key={skill.name} onClick={() => onSelectRecord(skill.recordIds[0])}>
                {skill.name} · {skill.accomplishmentCount} {skill.accomplishmentCount === 1 ? "story" : "stories"}
              </button>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
