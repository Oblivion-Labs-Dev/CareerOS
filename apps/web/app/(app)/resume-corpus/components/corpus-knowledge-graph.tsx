"use client";

import { SegmentedControl } from "@arsenal/ui";
import { useEffect, useMemo, useRef, useState } from "react";
import { CorpusEmptyState } from "@career-os/ui/corpus";
import type { CorpusRecord } from "../corpus-model";
import { recordCorpusPerformance } from "../corpus-performance";
import styles from "../resume-corpus.module.css";

type NodeType =
  | "accomplishment"
  | "company"
  | "project"
  | "skill"
  | "metric"
  | "architecture"
  | "evidence"
  | "concern"
  | "question"
  | "resume";
type ClusterMode = "company" | "domain" | "technology" | "none";

interface GraphNode {
  id: string;
  label: string;
  type: NodeType;
  x: number;
  y: number;
  recordId?: string;
}

interface GraphLink {
  source: string;
  target: string;
  label?: string;
}

interface CorpusKnowledgeGraphProps {
  records: CorpusRecord[];
  onSelectRecord: (recordId: string) => void;
}

function stableHash(value: string): number {
  return [...value].reduce((hash, character) => ((hash * 31) + character.charCodeAt(0)) >>> 0, 7);
}

function clusterKey(record: CorpusRecord, cluster: Exclude<ClusterMode, "none">): string {
  if (cluster === "company") return record.company || "Company not set";
  if (cluster === "domain") return record.domains[0] || "Domain not set";
  return record.technologies[0] || "Technology not set";
}

function applyClusterLayout(
  graph: { nodes: GraphNode[]; links: GraphLink[] },
  records: CorpusRecord[],
  cluster: ClusterMode,
): { nodes: GraphNode[]; links: GraphLink[] } {
  if (cluster === "none") return graph;
  const recordById = new Map(records.map((record) => [record.id, record]));
  const accomplishmentNodes = graph.nodes.filter((node) => node.type === "accomplishment" && node.recordId);
  const groups = new Map<string, GraphNode[]>();
  accomplishmentNodes.forEach((node) => {
    const record = recordById.get(node.recordId!);
    const key = record ? clusterKey(record, cluster) : "Other";
    groups.set(key, [...(groups.get(key) ?? []), node]);
  });
  const entries = [...groups.entries()].sort(([left], [right]) => left.localeCompare(right));
  const positions = new Map<string, { x: number; y: number }>();
  entries.forEach(([, members], groupIndex) => {
    const groupAngle = (groupIndex / Math.max(entries.length, 1)) * Math.PI * 2 - Math.PI / 2;
    const centerX = entries.length === 1 ? 450 : 450 + Math.cos(groupAngle) * 235;
    const centerY = entries.length === 1 ? 260 : 260 + Math.sin(groupAngle) * 145;
    members.forEach((node, memberIndex) => {
      const memberAngle = (memberIndex / Math.max(members.length, 1)) * Math.PI * 2;
      positions.set(node.id, {
        x: centerX + Math.cos(memberAngle) * (members.length === 1 ? 0 : 48),
        y: centerY + Math.sin(memberAngle) * (members.length === 1 ? 0 : 38),
      });
    });
  });

  const nodes = graph.nodes.map((node) => {
    const directPosition = positions.get(node.id);
    if (directPosition) return { ...node, ...directPosition };
    const connectingLink = graph.links.find((link) =>
      (link.source === node.id && positions.has(link.target)) || (link.target === node.id && positions.has(link.source)),
    );
    if (!connectingLink) return node;
    const accomplishmentId = positions.has(connectingLink.source) ? connectingLink.source : connectingLink.target;
    const anchor = positions.get(accomplishmentId)!;
    const angle = (stableHash(node.id) % 360) * (Math.PI / 180);
    const distance = node.type === "company" || node.type === "project" ? 92 : 68;
    return {
      ...node,
      x: Math.max(28, Math.min(872, anchor.x + Math.cos(angle) * distance)),
      y: Math.max(28, Math.min(492, anchor.y + Math.sin(angle) * distance)),
    };
  });
  return { nodes, links: graph.links };
}

function buildGraph(records: CorpusRecord[], cluster: ClusterMode): { nodes: GraphNode[]; links: GraphLink[] } {
  const nodes: GraphNode[] = [];
  const links: GraphLink[] = [];
  const seen = new Set<string>();
  const width = 900;
  const height = 520;

  records.forEach((record, index) => {
    const angle = (index / Math.max(records.length, 1)) * Math.PI * 2;
    const radius = 140;
    const accId = `acc-${record.id}`;
    if (!seen.has(accId)) {
      nodes.push({
        id: accId,
        label: record.title,
        type: "accomplishment",
        x: width / 2 + Math.cos(angle) * radius,
        y: height / 2 + Math.sin(angle) * radius,
        recordId: record.id,
      });
      seen.add(accId);
    }

    const companyId = `company-${record.company}`;
    if (!seen.has(companyId)) {
      nodes.push({
        id: companyId,
        label: record.company,
        type: "company",
        x: width / 2 + Math.cos(angle) * (radius + 90),
        y: height / 2 + Math.sin(angle) * (radius + 90),
      });
      seen.add(companyId);
    }
    links.push({ source: accId, target: companyId, label: "at" });

    const addRelatedNode = (id: string, label: string, type: NodeType, offset: number, linkLabel: string) => {
      if (!label.trim()) return;
      if (!seen.has(id)) {
        nodes.push({
          id,
          label,
          type,
          x: width / 2 + Math.cos(angle + offset) * (radius + 55),
          y: height / 2 + Math.sin(angle + offset) * (radius + 55),
          recordId: record.id,
        });
        seen.add(id);
      }
      links.push({ source: accId, target: id, label: linkLabel });
    };

    addRelatedNode(`project-${record.id}`, record.project, "project", 0.15, "delivered");
    addRelatedNode(`architecture-${record.id}`, record.architectureDecision, "architecture", 0.55, "decided");
    record.evidence.slice(0, 2).forEach((item, itemIndex) =>
      addRelatedNode(`evidence-${item.id}`, item.name, "evidence", 0.75 + itemIndex * 0.14, "supported by"),
    );
    record.concerns.slice(0, 1).forEach((concern) =>
      addRelatedNode(`concern-${concern.id}`, concern.concern, "concern", 1.05, "challenged by"),
    );
    record.interviewQuestions.slice(0, 1).forEach((question) =>
      addRelatedNode(`question-${question.id}`, question.question, "question", 1.25, "tested by"),
    );
    record.resumeVariants.slice(0, 1).forEach((variant) =>
      addRelatedNode(`resume-${variant.id}`, variant.name, "resume", 1.45, "published as"),
    );

    record.technologies.slice(0, 4).forEach((tech, techIndex) => {
      const techId = `skill-${tech.toLowerCase()}`;
      if (!seen.has(techId)) {
        nodes.push({
          id: techId,
          label: tech,
          type: "skill",
          x: width / 2 + Math.cos(angle + techIndex * 0.2) * (radius - 70),
          y: height / 2 + Math.sin(angle + techIndex * 0.2) * (radius - 70),
        });
        seen.add(techId);
      }
      links.push({ source: accId, target: techId, label: "uses" });
    });

    record.metrics.slice(0, 2).forEach((metric) => {
      const metricId = `metric-${metric.id}`;
      if (!seen.has(metricId)) {
        nodes.push({
          id: metricId,
          label: `${metric.name}: ${metric.value}`,
          type: "metric",
          x: width / 2 + Math.cos(angle + 0.4) * (radius + 40),
          y: height / 2 + Math.sin(angle + 0.4) * (radius + 40),
          recordId: record.id,
        });
        seen.add(metricId);
      }
      links.push({ source: accId, target: metricId, label: "measured" });
    });
  });

  return applyClusterLayout(
    { nodes: nodes.slice(0, 80), links: links.slice(0, 120) },
    records,
    cluster,
  );
}

export function CorpusKnowledgeGraph({ records, onSelectRecord }: CorpusKnowledgeGraphProps) {
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const [cluster, setCluster] = useState<ClusterMode>("company");
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const svgRef = useRef<SVGSVGElement>(null);
  const renderStartedAt = useRef(0);

  const graph = useMemo(() => {
    renderStartedAt.current = typeof window === "undefined" ? 0 : window.performance.now();
    return buildGraph(records, cluster);
  }, [cluster, records]);

  useEffect(() => {
    recordCorpusPerformance("graph-ready", window.performance.now() - renderStartedAt.current, { nodes: graph.nodes.length, links: graph.links.length, cluster });
  }, [cluster, graph]);

  const filteredNodes = useMemo(() => {
    const terms = query.trim().toLowerCase();
    if (!terms) return graph.nodes;
    return graph.nodes.filter((node) => node.label.toLowerCase().includes(terms));
  }, [graph.nodes, query]);

  const visibleLinks = useMemo(() => {
    const ids = new Set(filteredNodes.map((node) => node.id));
    if (focusedId) {
      return graph.links.filter((link) => link.source === focusedId || link.target === focusedId);
    }
    return graph.links.filter((link) => ids.has(link.source) && ids.has(link.target));
  }, [filteredNodes, focusedId, graph.links]);

  useEffect(() => {
    setFocusedId(null);
  }, [query, cluster]);

  if (records.length === 0) {
    return (
      <CorpusEmptyState
        title="Nothing to graph yet"
        description="Add accomplishments to see relationships between companies, skills, metrics, and evidence."
      />
    );
  }

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Knowledge Graph</div>
          <h1>Explore career relationships</h1>
          <p>Start focused, expand progressively, and switch to list view for accessibility.</p>
        </div>
        <SegmentedControl
          label="Graph mode"
          value={mode}
          onValueChange={(value) => setMode(value as "graph" | "list")}
          options={[
            { value: "graph", label: "Graph" },
            { value: "list", label: "List" },
          ]}
        />
      </header>

      <div className={styles.toolbar}>
        <input
          className={styles.toolbarSearch}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder="Search nodes…"
          aria-label="Search graph nodes"
        />
        <select
          className={styles.savedViewSelect}
          value={cluster}
          onChange={(event) => setCluster(event.currentTarget.value as ClusterMode)}
          aria-label="Cluster mode"
        >
          <option value="company">Cluster by company</option>
          <option value="domain">Cluster by domain</option>
          <option value="technology">Cluster by technology</option>
          <option value="none">No clustering</option>
        </select>
      </div>

      {mode === "list" ? (
        <section className={styles.panel}>
          <div className={styles.compactList}>
            {filteredNodes.map((node) => (
              <button
                key={node.id}
                type="button"
                className={styles.compactRow}
                onClick={() => node.recordId && onSelectRecord(node.recordId)}
              >
                <span><strong>{node.label}</strong><span>{node.type}</span></span>
                <span className={styles.statusTag}>{node.type}</span>
              </button>
            ))}
          </div>
        </section>
      ) : (
        <section className={styles.graphCanvas} aria-label="Knowledge graph canvas">
          <svg ref={svgRef} viewBox="0 0 900 520" role="group" aria-label="Interactive knowledge graph">
            {visibleLinks.map((link) => {
              const source = graph.nodes.find((node) => node.id === link.source);
              const target = graph.nodes.find((node) => node.id === link.target);
              if (!source || !target) return null;
              return (
                <line
                  key={`${link.source}-${link.target}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke="currentColor"
                  strokeOpacity={0.18}
                />
              );
            })}
            {filteredNodes.map((node) => (
              <g
                key={node.id}
                transform={`translate(${node.x}, ${node.y})`}
                role="button"
                tabIndex={0}
                aria-label={`${node.type}: ${node.label}`}
                onClick={() => {
                  setFocusedId(node.id);
                  if (node.recordId) onSelectRecord(node.recordId);
                }}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  setFocusedId(node.id);
                  if (node.recordId) onSelectRecord(node.recordId);
                }}
                style={{ cursor: "pointer" }}
              >
                <circle r={node.type === "accomplishment" ? 16 : 11} fill="var(--corpus-accent-soft)" stroke="var(--corpus-accent)" />
                <text y={28} textAnchor="middle" fontSize="10" fill="currentColor">{node.label.slice(0, 24)}</text>
              </g>
            ))}
          </svg>
          {focusedId ? (
            <p className={styles.helper}>
              Focused on {graph.nodes.find((node) => node.id === focusedId)?.label ?? "selection"}. Click another node to refocus.
            </p>
          ) : null}
        </section>
      )}
    </div>
  );
}
