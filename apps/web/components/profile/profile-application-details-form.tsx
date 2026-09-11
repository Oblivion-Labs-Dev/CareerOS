"use client";

import { useEffect, useMemo, useState } from "react";
import { postJson } from "@/lib/api";
import type { UserProfile } from "@career-os/core";

type ApplyPilotProfile = Partial<UserProfile> & Record<string, unknown>;

type Field = {
  key: string;
  label: string;
  hint?: string;
  placeholder?: string;
};

type Group = { group: string; blurb: string; fields: Field[] };

/**
 * The fields application forms ask for that the rest of the profile UI never
 * exposed. Everything here is read straight off the profile by the answer
 * resolver, so a blank value is not cosmetic — it is a required field the
 * automation has to leave empty, which stages the whole application for review.
 *
 * Mailing address is the clearest case: it lived only in a learned answer
 * captured from a past manual application, so forms were being filled from a
 * postcode that did not match where the candidate actually lives.
 */
const GROUPS: Group[] = [
  {
    group: "Mailing address",
    blurb:
      "Used for the address, city, state and postcode fields on application forms. These must match where you actually live.",
    fields: [
      { key: "streetAddress", label: "Street address", placeholder: "123 Example St" },
      { key: "city", label: "City", placeholder: "Seattle" },
      { key: "state", label: "State", placeholder: "Washington" },
      { key: "zip", label: "ZIP / postcode", placeholder: "98101" },
      { key: "country", label: "Country", placeholder: "United States" },
      {
        key: "location",
        label: "Location shown on applications",
        hint: "What a “Location — City, State” field should say.",
        placeholder: "Seattle, WA",
      },
    ],
  },
  {
    group: "Availability & relocation",
    blurb: "Answers the “when can you start?” and “are you willing to relocate?” questions.",
    fields: [
      {
        key: "noticePeriod",
        label: "Notice period / earliest start",
        hint: "Left blank, these questions go to Review instead of being answered.",
        placeholder: "2 weeks from offer",
      },
      {
        key: "relocate",
        label: "Willing to relocate",
        hint: "Yes or No. Blank means the question is left for you to answer per job.",
        placeholder: "Yes",
      },
    ],
  },
  {
    group: "Languages",
    blurb:
      "Answers the “which languages do you speak” checkbox groups some employers require (Lever boards ask this).",
    fields: [
      {
        key: "languages",
        label: "Languages you speak",
        hint: "Comma separated. Blank means the question goes to Review rather than being guessed at.",
        placeholder: "English",
      },
    ],
  },
  {
    group: "Compensation & links",
    blurb:
      "Answers the salary-expectation and profile-link questions that ATS forms mark required. Blank sends the whole application to Review.",
    fields: [
      {
        key: "salaryExpectations",
        label: "Annual salary expectations",
        hint: "What a “What are your salary expectations?” field should say.",
        placeholder: "$160,000",
      },
      {
        key: "github",
        label: "GitHub profile",
        placeholder: "https://github.com/yourname",
      },
      {
        key: "linkedin",
        label: "LinkedIn profile",
        placeholder: "https://www.linkedin.com/in/yourname/",
      },
      {
        key: "portfolio",
        label: "Portfolio / website",
        placeholder: "https://example.com",
      },
    ],
  },
  {
    group: "Education",
    blurb: "Fills the school, degree and graduation-year block that most ATS forms require.",
    fields: [
      { key: "school", label: "School", placeholder: "Santa Clara University" },
      { key: "degree", label: "Degree", placeholder: "Master's Degree" },
      { key: "discipline", label: "Field of study", placeholder: "Computer Science" },
      {
        key: "gpa",
        label: "Undergraduate GPA",
        hint: "Blank means GPA questions go to Review — a GPA is never guessed.",
        placeholder: "3.34",
      },
      { key: "graduateGpa", label: "Graduate GPA", placeholder: "3.77" },
    ],
  },
  {
    group: "Screening answers",
    blurb:
      "Yes/No facts application forms ask for that only you can state. Blank sends the question to Review rather than having it answered.",
    fields: [
      {
        key: "mayContactCurrentEmployer",
        label: "May we contact your current employer?",
        hint: "Yes or No.",
        placeholder: "Yes",
      },
      {
        key: "usCitizen",
        label: "Are you a U.S. citizen?",
        hint: "Yes or No. Never inferred from work authorization.",
        placeholder: "No",
      },
      {
        key: "exportControlStatus",
        label: "Export-control / ITAR status",
        hint: "The exact category these forms list, e.g. “U.S. permanent resident (Green Card holder)”.",
        placeholder: "U.S. permanent resident (Green Card holder)",
      },
    ],
  },
];

const ALL_KEYS = GROUPS.flatMap((group) => group.fields.map((field) => field.key));

export function ProfileApplicationDetailsForm({
  profile,
  onSaved,
}: {
  profile: ApplyPilotProfile;
  onSaved: () => void;
}) {
  const initial = useMemo(() => {
    const seed: Record<string, string> = {};
    for (const key of ALL_KEYS) {
      const value = profile[key];
      seed[key] = typeof value === "string" ? value : "";
    }
    return seed;
  }, [profile]);

  const [values, setValues] = useState<Record<string, string>>(initial);
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // Re-seed whenever the profile is reloaded, so a save elsewhere on the page
  // does not leave these inputs showing stale values.
  useEffect(() => setValues(initial), [initial]);

  const dirty = ALL_KEYS.some((key) => (values[key] || "") !== (initial[key] || ""));

  // The profile prop arrives empty on the first render and is filled in once
  // the page's fetch resolves. Saving in that window used to spread an empty
  // object and then delete every key this form manages, writing back a profile
  // stripped of the candidate's address, education and salary. Refuse to save
  // until there is a profile to merge into.
  const profileLoaded = Object.keys(profile || {}).length > 0;

  const save = async () => {
    if (!profileLoaded) {
      setNote("Still loading your profile — try again in a moment.");
      return;
    }
    setSaving(true);
    setNote(null);
    try {
      const next: ApplyPilotProfile = { ...profile };
      for (const key of ALL_KEYS) {
        const value = (values[key] || "").trim();
        if (value) next[key] = value;
        // A blank input clears that one field. It must never delete a key the
        // form never rendered a value for - that is how an unhydrated render
        // turned a Save click into data loss.
        else if (key in profile) next[key] = "";
      }
      // Keep the duplicate keys the resolver also reads in step with the
      // canonical ones, so a form asking for "postal code" and one asking for
      // "zip" cannot disagree.
      const custom: Record<string, string> = { ...((next.customFields as Record<string, string>) || {}) };
      if (next.zip) {
        custom.zip = String(next.zip);
        custom.postalCode = String(next.zip);
      }
      if (next.city) custom.city = String(next.city);
      if (next.state) custom.state = String(next.state);
      if (next.country) custom.country = String(next.country);
      if (next.streetAddress) custom.address = String(next.streetAddress);
      next.customFields = custom;

      await postJson("/profile", { profile: next });
      setNote("Saved. New applications will use these values.");
      onSaved();
    } catch (error) {
      setNote(error instanceof Error ? error.message : "Could not save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="workflow-panel dashboard-panel--wide" id="application-details" aria-label="Application details">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Used by Autopilot</span>
          <h2>Application details</h2>
          <p className="muted" style={{ marginTop: "0.35rem" }}>
            Answers Autopilot needs to fill a form without guessing. A blank field here is a question it will stop and
            ask you about instead of answering.
          </p>
        </div>
      </div>

      {GROUPS.map((group) => (
        <div key={group.group} style={{ marginTop: "1.25rem" }}>
          <h3 style={{ margin: 0, fontSize: "0.95rem" }}>{group.group}</h3>
          <p className="muted" style={{ margin: "0.25rem 0 0.75rem" }}>{group.blurb}</p>
          <div
            style={{
              display: "grid",
              gap: "0.75rem",
              gridTemplateColumns: "repeat(auto-fit, minmax(15rem, 1fr))",
            }}
          >
            {group.fields.map((field) => (
              <label key={field.key} style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                <span style={{ fontSize: "0.8rem", fontWeight: 600 }}>{field.label}</span>
                <input
                  type="text"
                  name={field.key}
                  aria-label={field.label}
                  value={values[field.key] || ""}
                  placeholder={field.placeholder}
                  onChange={(event) =>
                    setValues((previous) => ({ ...previous, [field.key]: event.target.value }))
                  }
                  style={{
                    padding: "0.5rem 0.65rem",
                    borderRadius: "0.5rem",
                    border: "1px solid var(--border, #d4d4d8)",
                    background: "var(--surface, #fff)",
                    // Explicit, not `inherit`: on the dark panel the inherited
                    // muted colour made a real value look identical to the
                    // placeholder, so a filled field read as empty.
                    color: "var(--text-strong, var(--foreground, #111))",
                    font: "inherit",
                  }}
                />
                {field.hint ? (
                  <span className="muted" style={{ fontSize: "0.75rem" }}>{field.hint}</span>
                ) : null}
              </label>
            ))}
          </div>
        </div>
      ))}

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "1.25rem" }}>
        <button type="button" className="btn btn-primary" disabled={saving || !dirty || !profileLoaded} onClick={() => void save()}>
          {saving ? "Saving…" : "Save application details"}
        </button>
        {note ? <span className="muted">{note}</span> : null}
      </div>
    </section>
  );
}
