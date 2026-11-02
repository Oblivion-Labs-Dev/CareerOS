"use client";

import { useState } from "react";
import { postJson } from "@/lib/api";

type Props = {
  extracted: Record<string, unknown>;
  profile: Record<string, unknown>;
  onSaved: () => void;
  onDismiss: () => void;
};

type FieldDef = { key: string; label: string; placeholder?: string };

const GROUPS: { title: string; fields: FieldDef[] }[] = [
  {
    title: "Contact",
    fields: [
      { key: "fullName", label: "Full name", placeholder: "Sumeet Suryawanshi" },
      { key: "email", label: "Email", placeholder: "you@example.com" },
      { key: "phone", label: "Phone", placeholder: "+1 (555) 000-0000" },
    ],
  },
  {
    title: "Location",
    fields: [
      { key: "location", label: "Location (shown on forms)", placeholder: "Seattle, WA" },
      { key: "country", label: "Country", placeholder: "United States" },
    ],
  },
  {
    title: "Links",
    fields: [
      { key: "linkedin", label: "LinkedIn", placeholder: "https://linkedin.com/in/yourname" },
      { key: "github", label: "GitHub", placeholder: "https://github.com/yourname" },
      { key: "portfolio", label: "Portfolio", placeholder: "https://yoursite.dev" },
    ],
  },
  {
    title: "Education (most recent)",
    fields: [
      { key: "school", label: "School", placeholder: "Arizona State University" },
      { key: "degree", label: "Degree", placeholder: "Master's Degree" },
      { key: "discipline", label: "Field of study", placeholder: "Computer Science" },
    ],
  },
  {
    title: "Current role",
    fields: [
      { key: "currentTitle", label: "Current title", placeholder: "Software Engineer" },
      { key: "currentCompany", label: "Current company", placeholder: "Acme Corp" },
    ],
  },
];

export function ResumeScanReview({ extracted, profile, onSaved, onDismiss }: Props) {
  const merged: Record<string, string> = {};
  for (const group of GROUPS) {
    for (const f of group.fields) {
      const v = extracted[f.key] ?? profile[f.key];
      merged[f.key] = typeof v === "string" ? v : "";
    }
  }

  const [values, setValues] = useState<Record<string, string>>(merged);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const skillsArr = Array.isArray(extracted.skills) ? extracted.skills as unknown[] : [];
  const skillCount = skillsArr.length;

  const set = (key: string, val: string) =>
    setValues((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      const payload: Record<string, unknown> = { ...values };
      const nameParts = (values.fullName || "").trim().split(/\s+/);
      if (nameParts.length >= 2) {
        payload.firstName = nameParts[0];
        payload.lastName = nameParts.slice(1).join(" ");
      }
      if (extracted.skills) payload.skills = extracted.skills;
      if (extracted.education) payload.education = extracted.education;
      if (extracted.workExperience) payload.workExperience = extracted.workExperience;
      await postJson("/profile", payload);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
      setSaving(false);
    }
  };

  return (
    <div className="resume-scan-review" role="region" aria-label="Resume scan results">
      <div className="resume-scan-review__header">
        <span className="toc-card-kicker">Scan complete</span>
        <h3>Review what we found — edit anything before saving</h3>
        <p className="muted" style={{ marginTop: "0.25rem", fontSize: "0.875rem" }}>
          Fields highlighted in teal were extracted from your resume. Blank fields were not found — fill them in manually.
          {skillCount > 0 && (
            <span> &nbsp;·&nbsp; <strong>{skillCount} skills</strong> extracted and saved automatically.</span>
          )}
        </p>
      </div>

      <div className="resume-scan-review__groups">
        {GROUPS.map((group) => {
          const anyExtracted = group.fields.some((f) => extracted[f.key]);
          return (
            <div key={group.title} className="resume-scan-review__group">
              <span className="toc-card-kicker" style={{ fontSize: "0.7rem" }}>{group.title}</span>
              {group.fields.map((f) => {
                const wasExtracted = Boolean(extracted[f.key]);
                return (
                  <div key={f.key} className="resume-scan-review__row">
                    <label className="resume-scan-review__label" htmlFor={`scan-${f.key}`}>
                      {f.label}
                    </label>
                    <input
                      id={`scan-${f.key}`}
                      className={`resume-scan-review__input${wasExtracted ? " resume-scan-review__input--extracted" : ""}`}
                      value={values[f.key] ?? ""}
                      placeholder={f.placeholder}
                      onChange={(e) => set(f.key, e.target.value)}
                    />
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>

      {error && (
        <p className="profile-documents-message profile-documents-message--error" role="alert">
          {error}
        </p>
      )}

      <div className="resume-scan-review__actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void handleSave()}
          disabled={saving}
        >
          {saving ? "Saving…" : "Save to profile"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onDismiss} disabled={saving}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
