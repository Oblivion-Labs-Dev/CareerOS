"use client";

import { useLayoutEffect, useState, type RefObject } from "react";
import styles from "./studio.module.css";

export type ReviewRequirement = { id: string; text: string };
export type ReviewBullet = {
  id: string;
  decision: "KEEP" | "REORDER" | "REPLACE";
  optimizedBullet: string;
  original?: string;
  requirementIds: string[];
  requirementPercents?: Record<string, number>;
  slotRect?: number[];
  selectionReason: string;
  source?: { field: string };
};

const THREAD_COLORS = ["#7eb6ff", "#e0b15a", "#c58bff", "#3ecf8e", "#f0a0c0", "#9ad07a"];

export function threadColor(index: number) {
  return THREAD_COLORS[index % THREAD_COLORS.length];
}

export function locateClause(description: string, needle: string): { start: number; end: number } | null {
  const exact = description.indexOf(needle);
  if (exact >= 0) return { start: exact, end: exact + needle.length };
  const pattern = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
  const match = description.match(new RegExp(pattern, "i"));
  if (!match || match.index === undefined) return null;
  return { start: match.index, end: match.index + match[0].length };
}

function wordParts(next: string, original: string) {
  const known = new Set(original.toLowerCase().split(/\W+/).filter(Boolean));
  return next.split(/(\s+)/).map((part) => {
    const token = part.toLowerCase().replace(/^[^\w]+|[^\w]+$/g, "");
    return { part, added: Boolean(token) && !known.has(token) };
  });
}

export function linkPercent(bullet: Pick<ReviewBullet, "optimizedBullet" | "requirementPercents">, requirement: ReviewRequirement): number {
  const recorded = bullet.requirementPercents?.[requirement.id];
  if (typeof recorded === "number") return recorded;
  const words = (text: string) => new Set(text.toLowerCase().split(/\W+/).filter((word) => word.length > 2));
  const requested = [...words(requirement.text)];
  if (!requested.length) return 0;
  const present = words(bullet.optimizedBullet);
  return Math.round(100 * requested.filter((word) => present.has(word)).length / requested.length);
}

export type ThreadPath = {
  id: string;
  reqId: string;
  bulletId: string;
  color: string;
  percent: number;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

export function useMatchThreads(rootRef: RefObject<HTMLElement | null>, enabled: boolean, signature: string) {
  const [paths, setPaths] = useState<ThreadPath[]>([]);
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root || !enabled) {
      setPaths([]);
      return;
    }
    const measure = () => {
      const box = root.getBoundingClientRect();
      const next: ThreadPath[] = [];
      root.querySelectorAll<HTMLElement>("[data-bullet]").forEach((bullet) => {
        const bulletId = bullet.dataset.bullet || "";
        const reqs = (bullet.dataset.reqs || "").split(",").filter(Boolean);
        const percents = Object.fromEntries((bullet.dataset.match || "").split("|").filter(Boolean).map((pair) => {
          const [id, value] = pair.split(":");
          return [id, Number(value)];
        }));
        const target = bullet.getBoundingClientRect();
        reqs.forEach((reqId) => {
          const mark = root.querySelector<HTMLElement>(`[data-req="${CSS.escape(reqId)}"]`);
          if (!mark) return;
          const source = mark.getBoundingClientRect();
          const viewport = mark.closest<HTMLElement>("[role=region]")?.getBoundingClientRect();
          if (viewport && (source.bottom < viewport.top || source.top > viewport.bottom)) return;
          next.push({
            id: `${bulletId}-${reqId}`,
            reqId,
            bulletId,
            color: mark.dataset.color || THREAD_COLORS[0],
            percent: Number.isFinite(percents[reqId]) ? percents[reqId] : 0,
            x1: source.right - box.left,
            y1: source.top + source.height / 2 - box.top,
            x2: target.left - box.left,
            y2: target.top + target.height / 2 - box.top,
          });
        });
      });
      setPaths(next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(root);
    root.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      root.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [rootRef, enabled, signature]);
  return paths;
}

export function ThreadLayer({ paths, active }: { paths: ThreadPath[]; active: string | null }) {
  return (
    <svg className={styles.threadLayer} aria-hidden="true">
      {paths.map((path) => {
        const hot = !active || active === path.bulletId || active === path.reqId;
        const midX = (path.x1 + path.x2) / 2;
        const midY = (path.y1 + path.y2) / 2;
        const d = `M ${path.x1} ${path.y1} C ${midX} ${path.y1}, ${midX} ${path.y2}, ${path.x2} ${path.y2}`;
        const label = `${path.percent}%`;
        return (
          <g key={path.id} opacity={hot ? 0.95 : 0.14}>
            <path d={d} fill="none" stroke={path.color} strokeWidth={hot ? 2.25 : 1.25} />
            <circle cx={path.x1} cy={path.y1} r={3.5} fill={path.color} />
            <circle cx={path.x2} cy={path.y2} r={3.5} fill={path.color} />
            <g transform={`translate(${midX} ${midY})`}>
              <rect x={-16} y={-8} width={32} height={16} rx={4} fill="#121816" stroke={path.color} />
              <text x={0} y={4} textAnchor="middle" fill={path.color} fontSize="9" fontFamily="sans-serif">{label}</text>
            </g>
          </g>
        );
      })}
    </svg>
  );
}

export function JobDescriptionMarks({
  description,
  requirements,
  linkedIds,
  active,
  activeRequirementIds = [],
  onHover,
}: {
  description: string;
  requirements: ReviewRequirement[];
  linkedIds: string[];
  active: string | null;
  activeRequirementIds?: string[];
  onHover: (id: string | null) => void;
}) {
  const linked = new Set(linkedIds);
  const colorFor = new Map(requirements.map((requirement, index) => [requirement.id, threadColor(index)]));
  const found: Array<ReviewRequirement & { start: number; end: number }> = [];
  const missing: ReviewRequirement[] = [];
  requirements.filter((requirement) => linked.has(requirement.id)).forEach((requirement) => {
    const span = locateClause(description, requirement.text);
    if (span) found.push({ ...requirement, ...span });
    else missing.push(requirement);
  });
  found.sort((left, right) => left.start - right.start);
  const parts: Array<{ text: string; reqId?: string }> = [];
  let cursor = 0;
  found.forEach((requirement) => {
    if (requirement.start < cursor) return;
    if (requirement.start > cursor) parts.push({ text: description.slice(cursor, requirement.start) });
    parts.push({ text: description.slice(requirement.start, requirement.end), reqId: requirement.id });
    cursor = requirement.end;
  });
  if (cursor < description.length) parts.push({ text: description.slice(cursor) });

  return (
    <div className={styles.jdReading} role="region" aria-label="Job description with the lines that drove additions">
      <p>
        {parts.map((part, index) => part.reqId ? (
          <mark
            key={`${part.reqId}-${index}`}
            data-req={part.reqId}
            data-color={colorFor.get(part.reqId)}
            data-hot={!active || active === part.reqId || activeRequirementIds.includes(part.reqId) ? "true" : "false"}
            style={{ ["--thread" as string]: colorFor.get(part.reqId) }}
            onMouseEnter={() => onHover(part.reqId || null)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(part.reqId || null)}
            onBlur={() => onHover(null)}
            tabIndex={0}
          >{part.text}</mark>
        ) : <span key={index}>{part.text}</span>)}
      </p>
      {missing.map((requirement) => (
        <mark
          key={requirement.id}
          data-req={requirement.id}
          data-color={colorFor.get(requirement.id)}
          data-hot={!active || active === requirement.id || activeRequirementIds.includes(requirement.id) ? "true" : "false"}
          style={{ ["--thread" as string]: colorFor.get(requirement.id) }}
          onMouseEnter={() => onHover(requirement.id)}
          onMouseLeave={() => onHover(null)}
        >{requirement.text}</mark>
      ))}
    </div>
  );
}

export function AddedRegions({
  bullets,
  requirements,
  pageRect,
  active,
  onHover,
}: {
  bullets: Array<ReviewBullet & { key: string }>;
  requirements: ReviewRequirement[];
  pageRect?: number[];
  active: string | null;
  onHover: (id: string | null) => void;
}) {
  const pageW = pageRect && pageRect.length === 4 ? pageRect[2] - pageRect[0] : 612;
  const pageH = pageRect && pageRect.length === 4 ? pageRect[3] - pageRect[1] : 792;
  const byId = new Map(requirements.map((requirement) => [requirement.id, requirement]));
  return (
    <>
      {bullets.map((bullet) => {
        const rect = bullet.slotRect;
        if (!rect || rect.length !== 4 || bullet.requirementIds.length === 0) return null;
        const hot = !active || active === bullet.key || bullet.requirementIds.includes(active);
        const added = bullet.decision === "REPLACE";
        const match = bullet.requirementIds.map((id) => {
          const requirement = byId.get(id);
          return `${id}:${requirement ? linkPercent(bullet, requirement) : 0}`;
        }).join("|");
        return (
          <button
            key={bullet.key}
            type="button"
            className={added ? styles.addedRegion : styles.matchRegion}
            data-bullet={bullet.key}
            data-reqs={bullet.requirementIds.join(",")}
            data-match={match}
            data-hot={hot ? "true" : "false"}
            style={{
              left: `${((rect[0] - (pageRect?.[0] || 0)) / pageW) * 100}%`,
              top: `${((rect[1] - (pageRect?.[1] || 0)) / pageH) * 100}%`,
              width: `${((rect[2] - rect[0]) / pageW) * 100}%`,
              height: `${((rect[3] - rect[1]) / pageH) * 100}%`,
            }}
            aria-label={added ? `Added, not on the approved resume: ${bullet.optimizedBullet}` : `Matched bullet: ${bullet.optimizedBullet}`}
            onMouseEnter={() => onHover(bullet.key)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(bullet.key)}
            onBlur={() => onHover(null)}
          />
        );
      })}
    </>
  );
}

export function AdditionReview({
  bullets,
  requirements,
  approvals,
  onDecision,
  active,
  onHover,
}: {
  bullets: Array<ReviewBullet & { key: string }>;
  requirements: ReviewRequirement[];
  approvals: Record<string, "approved" | "held">;
  onDecision: (key: string, decision: "approved" | "held") => void;
  active: string | null;
  onHover: (id: string | null) => void;
}) {
  if (bullets.length === 0) {
    return <p className={styles.reviewNote}>Aggressive mode did not add anything that was absent from the approved resume.</p>;
  }
  const pending = bullets.filter((bullet) => approvals[bullet.key] !== "approved");
  return (
    <div className={styles.approvalList}>
      <p>{pending.length === 0 ? "Every addition is approved. The PDF matches what you accepted." : `${pending.length} addition${pending.length === 1 ? " still needs" : "s still need"} approval. Red words were not in the approved line.`}</p>
      {bullets.map((bullet) => {
        const decision = approvals[bullet.key];
        const matched = requirements.filter((requirement) => bullet.requirementIds.includes(requirement.id));
        return (
          <article
            key={bullet.key}
            className={styles.approvalItem}
            data-hot={!active || active === bullet.key || bullet.requirementIds.includes(active) ? "true" : "false"}
            onMouseEnter={() => onHover(bullet.key)}
            onMouseLeave={() => onHover(null)}
          >
            <p>
              {wordParts(bullet.optimizedBullet, bullet.original || "").map((piece, index) => piece.added
                ? <mark key={index} className={styles.addedWord}>{piece.part}</mark>
                : <span key={index}>{piece.part}</span>)}
            </p>
            {bullet.original ? <small>Approved resume: {bullet.original}</small> : null}
            <small>{matched.length ? `Chosen for: ${matched.map((requirement) => requirement.text).join(" · ")}` : "No posting line was credited for this addition."}</small>
            <div className={styles.approvalActions}>
              <button type="button" data-choice={decision === "approved" ? "yes" : undefined} onClick={() => onDecision(bullet.key, "approved")}>Approve addition</button>
              <button type="button" data-choice={decision === "held" ? "no" : undefined} onClick={() => onDecision(bullet.key, "held")}>Not this one</button>
            </div>
          </article>
        );
      })}
    </div>
  );
}
