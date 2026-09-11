"use client";

import { useEffect, useMemo, useState } from "react";
import { postJson } from "@/lib/api";
import type { UserProfile } from "@career-os/core";

type ExperienceEntry = {
  jobTitle?: string;
  company?: string;
  location?: string;
  startDate?: string;
  endDate?: string;
  currentlyEmployed?: string | boolean;
  description?: string;
  [key: string]: unknown;
};

type ApplyPilotProfile = Partial<UserProfile> & Record<string, unknown>;

function isCurrent(entry: ExperienceEntry): boolean {
  const raw = entry.currentlyEmployed;
  return raw === true || String(raw).toLowerCase() === "true";
}

function dateLine(entry: ExperienceEntry): string {
  const end = entry.endDate || (isCurrent(entry) ? "Present" : "");
  return [entry.location, entry.startDate, end].filter(Boolean).join(" · ");
}

/**
 * The detail behind each role, which the profile page previously never showed.
 *
 * `workExperience[].description` is the single biggest input to match scoring —
 * `candidate_match_context.work_experience_text` reads it straight into the
 * summary the scorer sees. It was being written and read by the backend with no
 * way to view or correct it in the app, so a wrong or empty description was
 * invisible until scores came back low.
 */
export function ProfileExperienceSection({
  profile,
  onSaved,
}: {
  profile: ApplyPilotProfile;
  onSaved: () => void;
}) {
  const entries = useMemo<ExperienceEntry[]>(
    () => ((profile?.workExperience as ExperienceEntry[]) || []).filter(Boolean),
    [profile],
  );

  const initial = useMemo(() => entries.map((e) => String(e.description || "")), [entries]);
  const [drafts, setDrafts] = useState<string[]>(initial);
  const [editing, setEditing] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(entries.length ? 0 : null);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // Re-seed when the profile reloads so the textareas never show stale text.
  useEffect(() => setDrafts(initial), [initial]);

  const profileLoaded = Object.keys(profile || {}).length > 0;

  const save = async (index: number) => {
    if (!profileLoaded) {
      setNote("Still loading your profile — try again in a moment.");
      return;
    }
    setSaving(true);
    setNote(null);
    try {
      const nextExperience = entries.map((entry, i) =>
        i === index ? { ...entry, description: drafts[i] ?? "" } : entry,
      );
      await postJson("/profile", { profile: { ...profile, workExperience: nextExperience } });
      setNote(`Saved ${entries[index]?.company || "role"}. New applications will score against it.`);
      setEditing(null);
      onSaved();
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Could not save this role");
    } finally {
      setSaving(false);
    }
  };

  if (!entries.length) {
    return (
      <article className="workflow-panel dashboard-panel--wide" id="experience">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Experience</span>
            <h2>No work history saved yet</h2>
          </div>
        </div>
        <p className="muted dashboard-empty">
          Add roles to your profile and their detail will appear here.
        </p>
      </article>
    );
  }

  return (
    <article className="workflow-panel dashboard-panel--wide" id="experience">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Experience</span>
          <h2>{entries.length} roles</h2>
          <p className="muted" style={{ marginTop: "0.35rem" }}>
            What each role says here is what Autopilot scores your match against. Blank or thin
            detail is the most common reason a good role scores low.
          </p>
        </div>
      </div>

      {note && (
        <p className="muted" style={{ marginBottom: "0.75rem" }} role="status">
          {note}
        </p>
      )}

      <div className="profile-experience-list">
        {entries.map((entry, index) => {
          const text = drafts[index] ?? "";
          const open = expanded === index;
          const isEditing = editing === index;
          return (
            <section className="profile-experience-item" key={`${entry.company}-${index}`}>
              <header className="profile-experience-head">
                <div>
                  <h3>
                    {entry.jobTitle || "Role"} <span className="at">@</span>{" "}
                    {entry.company || "Company"}
                  </h3>
                  <span className="profile-experience-meta">{dateLine(entry)}</span>
                </div>
                <div className="profile-experience-controls">
                  <span
                    className="profile-experience-badge"
                    data-state={isCurrent(entry) ? "current" : "past"}
                  >
                    {isCurrent(entry) ? "Current" : "Past"}
                  </span>
                  <span className="profile-experience-count">
                    {text ? `${text.length.toLocaleString()} chars` : "empty"}
                  </span>
                  <button
                    type="button"
                    className="btn btn-xs btn-secondary"
                    aria-expanded={open}
                    onClick={() => setExpanded(open ? null : index)}
                  >
                    {open ? "Hide" : "Show"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-xs btn-secondary"
                    disabled={!profileLoaded}
                    onClick={() => {
                      setExpanded(index);
                      setEditing(isEditing ? null : index);
                    }}
                  >
                    {isEditing ? "Cancel" : "Edit"}
                  </button>
                </div>
              </header>

              {open && !isEditing && (
                <div className="profile-experience-body">
                  {text ? (
                    <pre>{text}</pre>
                  ) : (
                    <p className="muted">
                      No detail recorded. Autopilot has almost nothing to match this role against.
                    </p>
                  )}
                </div>
              )}

              {isEditing && (
                <div className="profile-experience-edit">
                  <label htmlFor={`experience-${index}`} className="sr-only">
                    Detail for {entry.jobTitle} at {entry.company}
                  </label>
                  <textarea
                    id={`experience-${index}`}
                    value={text}
                    rows={18}
                    onChange={(event) =>
                      setDrafts((prev) => {
                        const next = [...prev];
                        next[index] = event.target.value;
                        return next;
                      })
                    }
                  />
                  <div className="profile-experience-actions">
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={saving || !profileLoaded}
                      onClick={() => void save(index)}
                    >
                      {saving ? "Saving…" : "Save role"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm btn-secondary"
                      disabled={saving}
                      onClick={() => {
                        setDrafts(initial);
                        setEditing(null);
                      }}
                    >
                      Discard changes
                    </button>
                  </div>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </article>
  );
}
