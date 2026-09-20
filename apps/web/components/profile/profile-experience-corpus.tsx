"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";
import { renderStoryBody, trimStoryPreamble } from "./story-body";
import styles from "./experience-corpus.module.css";

/** A story as the map lists it — everything except the body text. */
type StorySummary = {
  id: string;
  title: string;
  company: string;
  kind: string;
  headline: string;
  evidence: string;
  strength: string;
  technologies: string[];
  technologyGroups: Record<string, string[]>;
  skills: string[];
  infrastructure: string[];
  concepts: string[];
  signals: string[];
  primary: string[];
  metrics: string[];
  doNotClaim: string[];
  approval: string;
  resumeUsable: boolean;
  chars: number;
};

type StoryMap = {
  stories: StorySummary[];
  totals: {
    stories: number;
    skills: number;
    byTier: Record<string, number>;
    byApproval: Record<string, number>;
    resumeUsable: number;
  };
};

const TIER_CLASS: Record<string, string> = {
  professional: styles.tierProfessional,
  "personal-project": styles.tierPersonal,
  planned: styles.tierPlanned,
};

const TIER_LABEL: Record<string, string> = {
  professional: "Professional",
  "personal-project": "Personal project",
  planned: "Not yet built",
};

/** What each approval state means for resume building, in the user's terms. */
const APPROVAL_LABEL: Record<string, string> = {
  approved: "You approved this for resumes",
  auto: "Cleared automatically — strong professional evidence",
  pending: "Not yet cleared for resumes",
  unverified: "Blocked: a metric on this story is unverified",
  declined: "You excluded this from resumes",
};

function TagRow({ tags, primary }: { tags: string[]; primary: Set<string> }) {
  return (
    <div className={styles.tags}>
      {tags.map((tag) => (
        <span key={tag} className={primary.has(tag) ? `${styles.tag} ${styles.tagPrimary}` : styles.tag}>
          {tag}
        </span>
      ))}
    </div>
  );
}

export function ProfileExperienceCorpus() {
  const [map, setMap] = useState<StoryMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [company, setCompany] = useState<string | null>(null);
  // Bodies are fetched one at a time and kept, so going back to a story you
  // already opened does not re-request a few thousand characters of prose.
  const [bodies, setBodies] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);

  /** Record a resume-approval decision and reflect the server's answer. */
  const decide = useCallback(async (id: string, approved: boolean | null) => {
    setSaving(id);
    try {
      const response = await fetch(
        `${getClientApiBaseUrl()}/story-map/stories/${encodeURIComponent(id)}/resume-approval`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved }),
        },
      );
      const data = await response.json();
      if (!response.ok || !data?.ok) return;
      setMap((prev) => prev && ({
        ...prev,
        stories: prev.stories.map((story) =>
          story.id === id ? { ...story, approval: data.approval, resumeUsable: data.resumeUsable } : story),
      }));
    } catch {
      // Leave the shown state alone; the next load reports the truth.
    } finally {
      setSaving(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetch(`${getClientApiBaseUrl()}/story-map`, { credentials: "include" })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then((data: StoryMap) => {
        if (cancelled) return;
        setMap(data);
        setSelectedId(data.stories[0]?.id ?? null);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load your experience corpus.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId || bodies[selectedId] !== undefined) return;
    let cancelled = false;
    void fetch(`${getClientApiBaseUrl()}/story-map/stories/${encodeURIComponent(selectedId)}`, { credentials: "include" })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data?.found) return;
        setBodies((prev) => ({ ...prev, [selectedId]: String(data.body || "") }));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [selectedId, bodies]);

  // Memoised because the fallback is a fresh [] on every render, which would
  // otherwise invalidate every derived memo below on each one.
  const stories = useMemo(() => map?.stories ?? [], [map]);

  const companies = useMemo(() => {
    const counts = new Map<string, number>();
    for (const story of stories) counts.set(story.company || "Personal", (counts.get(story.company || "Personal") ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [stories]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return stories.filter((story) => {
      if (company && (story.company || "Personal") !== company) return false;
      if (!needle) return true;
      // Search the tags as well as the text: the reason to look for "Kafka" is
      // to find the story tagged with it, which may never write the word in
      // its title.
      const haystack = [story.title, story.company, story.headline, ...story.technologies, ...story.concepts, ...story.signals]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [stories, query, company]);

  const grouped = useMemo(() => {
    const byCompany = new Map<string, StorySummary[]>();
    for (const story of filtered) {
      const key = story.company || "Personal";
      if (!byCompany.has(key)) byCompany.set(key, []);
      byCompany.get(key)!.push(story);
    }
    return [...byCompany.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  }, [filtered]);

  const selected = stories.find((story) => story.id === selectedId) ?? null;
  const primary = useMemo(() => new Set(selected?.primary ?? []), [selected]);

  if (error) return <p className="muted dashboard-empty">{error}</p>;
  if (!map) return <p className="muted dashboard-empty" role="status">Loading your experience corpus…</p>;

  const skillGroups = Object.entries(selected?.technologyGroups ?? {}).filter(([, tags]) =>
    tags.some((tag) => (selected?.skills ?? []).includes(tag)),
  );
  const infraGroups = Object.entries(selected?.technologyGroups ?? {}).filter(([, tags]) =>
    tags.some((tag) => (selected?.infrastructure ?? []).includes(tag)),
  );

  return (
    <>
      <p className={styles.summaryStrip}>
        <span><strong>{map.totals.stories}</strong> stories</span>
        <span><strong>{map.totals.skills}</strong> distinct skills evidenced</span>
        <span><strong>{map.totals.byTier.professional ?? 0}</strong> professional</span>
        <span><strong>{map.totals.byTier["personal-project"] ?? 0}</strong> personal projects</span>
        <span><strong>{stories.filter((story) => story.resumeUsable).length}</strong> cleared for resumes</span>
        <span><strong>{stories.filter((story) => story.approval === "pending").length}</strong> awaiting your review</span>
      </p>
      <div className={styles.corpus}>
        <nav className={styles.index} aria-label="Experience stories">
          <div className={styles.search}>
            <input
              type="search"
              value={query}
              placeholder="Search stories, skills, infrastructure…"
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Search experience stories"
            />
            <div className={styles.facets}>
              <button
                type="button"
                className={company === null ? `${styles.facet} ${styles.facetOn}` : styles.facet}
                onClick={() => setCompany(null)}
              >
                All {stories.length}
              </button>
              {companies.map(([name, count]) => (
                <button
                  key={name}
                  type="button"
                  className={company === name ? `${styles.facet} ${styles.facetOn}` : styles.facet}
                  onClick={() => setCompany(company === name ? null : name)}
                >
                  {name} {count}
                </button>
              ))}
            </div>
          </div>
          <div className={styles.list}>
            {grouped.length === 0 ? (
              <p className={styles.empty}>No story matches that.</p>
            ) : (
              grouped.map(([name, items]) => (
                <div key={name}>
                  <div className={styles.groupLabel}>{name}</div>
                  {items.map((story) => (
                    <button
                      key={story.id}
                      type="button"
                      className={story.id === selectedId ? `${styles.row} ${styles.rowOn}` : styles.row}
                      aria-current={story.id === selectedId}
                      onClick={() => setSelectedId(story.id)}
                    >
                      <span
                        className={`${styles.tier} ${TIER_CLASS[story.evidence] ?? ""}`}
                        title={TIER_LABEL[story.evidence] ?? story.evidence}
                        aria-hidden="true"
                      />
                      <span>{story.title}</span>
                      {story.resumeUsable ? (
                        <span className={styles.usable} title="Cleared for resumes" aria-hidden="true">R</span>
                      ) : null}
                    </button>
                  ))}
                </div>
              ))
            )}
          </div>
        </nav>

        <article className={styles.reader} aria-live="polite">
          {!selected ? (
            <p className={styles.readerEmpty}>Pick a story to read it in full.</p>
          ) : (
            <>
              <div className={styles.readerHead}>
                <span className={styles.readerCompany}>{selected.company || "Personal project"}</span>
                <span className={selected.evidence === "professional" ? styles.badge : `${styles.badge} ${styles.badgeWarn}`}>
                  {TIER_LABEL[selected.evidence] ?? selected.evidence}
                </span>
                <span className={styles.badge}>{selected.strength.replace(/_/g, " ")}</span>
                <span className={styles.badge}>{selected.kind.replace(/-/g, " ")}</span>
              </div>

              <div className={styles.approvalRow}>
                <span
                  className={
                    selected.resumeUsable
                      ? `${styles.approvalState} ${styles.approvalOn}`
                      : selected.approval === "unverified" || selected.approval === "declined"
                        ? `${styles.approvalState} ${styles.approvalOff}`
                        : styles.approvalState
                  }
                >
                  {APPROVAL_LABEL[selected.approval] ?? selected.approval}
                </span>
                {selected.approval === "unverified" ? (
                  <span className={styles.approvalNote}>
                    Verify the metric on this story before it can be used.
                  </span>
                ) : (
                  <span className={styles.approvalActions}>
                    <button
                      type="button"
                      className={selected.approval === "approved" ? styles.approvalBtnOn : styles.approvalBtn}
                      disabled={saving === selected.id}
                      onClick={() => void decide(selected.id, true)}
                    >
                      Use on resumes
                    </button>
                    <button
                      type="button"
                      className={selected.approval === "declined" ? styles.approvalBtnOn : styles.approvalBtn}
                      disabled={saving === selected.id}
                      onClick={() => void decide(selected.id, false)}
                    >
                      Never
                    </button>
                    {selected.approval === "approved" || selected.approval === "declined" ? (
                      <button
                        type="button"
                        className={styles.approvalBtn}
                        disabled={saving === selected.id}
                        onClick={() => void decide(selected.id, null)}
                      >
                        Clear
                      </button>
                    ) : null}
                  </span>
                )}
              </div>
              <h3 className={styles.readerTitle}>{selected.title}</h3>
              {selected.headline && <p className={styles.headline}>{selected.headline}</p>}

              {skillGroups.length > 0 && (
                <div className={styles.tagBlock}>
                  <span className={styles.tagBlockLabel}>Skills</span>
                  {skillGroups.map(([group, tags]) => (
                    <div key={group} className={styles.subGroup}>
                      <span className={styles.subGroupLabel}>{group}</span>
                      <TagRow tags={tags} primary={primary} />
                    </div>
                  ))}
                </div>
              )}

              {infraGroups.length > 0 && (
                <div className={styles.tagBlock}>
                  <span className={styles.tagBlockLabel}>Infrastructure</span>
                  {infraGroups.map(([group, tags]) => (
                    <div key={group} className={styles.subGroup}>
                      <span className={styles.subGroupLabel}>{group}</span>
                      <TagRow tags={tags} primary={primary} />
                    </div>
                  ))}
                </div>
              )}

              {selected.concepts.length > 0 && (
                <div className={styles.tagBlock}>
                  <span className={styles.tagBlockLabel}>Engineering concepts</span>
                  <TagRow tags={selected.concepts} primary={primary} />
                </div>
              )}

              {selected.signals.length > 0 && (
                <div className={styles.tagBlock}>
                  <span className={styles.tagBlockLabel}>Behavioural signals</span>
                  <TagRow tags={selected.signals} primary={primary} />
                </div>
              )}

              <div className={styles.split}>
                {selected.metrics.length > 0 && (
                  <div>
                    <span className={styles.tagBlockLabel}>Numbers you can cite</span>
                    <ul className={styles.factList}>
                      {selected.metrics.map((metric) => <li key={metric}>{metric}</li>)}
                    </ul>
                  </div>
                )}
                {selected.doNotClaim.length > 0 && (
                  <div>
                    <span className={styles.tagBlockLabel}>Do not claim</span>
                    <ul className={`${styles.factList} ${styles.warnList}`}>
                      {selected.doNotClaim.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                )}
              </div>

              <details className={styles.body} open>
                <summary>Full story · {selected.chars.toLocaleString()} characters</summary>
                <div className={styles.bodyText}>
                  {bodies[selected.id] === undefined ? (
                    <p className={styles.bodyParagraph}>Loading…</p>
                  ) : bodies[selected.id] ? (
                    renderStoryBody(trimStoryPreamble(bodies[selected.id]), styles)
                  ) : (
                    <p className={styles.bodyParagraph}>No body text saved for this story.</p>
                  )}
                </div>
              </details>
            </>
          )}
        </article>
      </div>
    </>
  );
}
