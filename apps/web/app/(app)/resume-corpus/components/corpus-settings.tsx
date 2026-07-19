"use client";

import { DisclosureSection } from "@arsenal/ui";
import { useState } from "react";
import type { CorpusProfile } from "../corpus-model";
import styles from "../resume-corpus.module.css";

interface CorpusSettingsProps {
  profile: CorpusProfile;
  previewMode: boolean;
  onProfileChange: (profile: CorpusProfile) => void;
  onSave?: (profile: CorpusProfile) => Promise<void>;
}

export function CorpusSettings({ profile, previewMode, onProfileChange, onSave }: CorpusSettingsProps) {
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const handleSave = async () => {
    if (!onSave) {
      setSaveMessage("Profile updated for this session.");
      return;
    }
    setSaving(true);
    setSaveMessage(null);
    try {
      await onSave(profile);
      setSaveMessage(previewMode ? "Saved in preview (local session only)." : "Profile saved.");
    } catch {
      setSaveMessage("Could not save profile. Try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.viewStack}>
      <header className={styles.sectionHeading}>
        <div>
          <div className={styles.eyebrow}>Settings</div>
          <h1>Corpus configuration</h1>
          <p>Positioning, taxonomies, and schemas stay configurable — not locked to one industry.</p>
        </div>
      </header>

      <section className={styles.panel}>
        <div className={styles.formStack}>
          <div className={styles.fieldGroup}>
            <label className={styles.label} htmlFor="profile-name">Full name</label>
            <input
              id="profile-name"
              className={styles.field}
              value={profile.fullName}
              onChange={(event) => onProfileChange({ ...profile, fullName: event.currentTarget.value })}
            />
          </div>
          <div className={styles.fieldGroup}>
            <label className={styles.label} htmlFor="profile-title">Current positioning</label>
            <input
              id="profile-title"
              className={styles.field}
              value={profile.currentTitle}
              onChange={(event) => onProfileChange({ ...profile, currentTitle: event.currentTarget.value })}
            />
          </div>
          <div className={styles.fieldGroup}>
            <label className={styles.label} htmlFor="profile-target">Target role</label>
            <input
              id="profile-target"
              className={styles.field}
              value={profile.targetRole}
              onChange={(event) => onProfileChange({ ...profile, targetRole: event.currentTarget.value })}
            />
          </div>
          <div className={styles.fieldGroup}>
            <label className={styles.label} htmlFor="profile-years">Years of experience</label>
            <input
              id="profile-years"
              className={styles.field}
              value={profile.yearsExperience}
              onChange={(event) => onProfileChange({ ...profile, yearsExperience: event.currentTarget.value })}
            />
          </div>
          <div className={styles.fieldGroup}>
            <label className={styles.label} htmlFor="profile-domains">Primary domains (comma-separated)</label>
            <input
              id="profile-domains"
              className={styles.field}
              value={profile.primaryDomains.join(", ")}
              onChange={(event) =>
                onProfileChange({
                  ...profile,
                  primaryDomains: event.currentTarget.value.split(",").map((value) => value.trim()).filter(Boolean),
                })
              }
            />
          </div>
          <div className={styles.workspaceActions}>
            <button type="button" className={styles.primaryButton} disabled={saving} onClick={() => void handleSave()}>
              {saving ? "Saving…" : "Save profile"}
            </button>
            {saveMessage ? <span className={styles.helper} role="status">{saveMessage}</span> : null}
          </div>
        </div>
      </section>

      <DisclosureSection title="Reviewer personas" defaultOpen={false}>
        <p className={styles.helper}>Configure which reviewer types generate concerns and interview questions. Defaults cover recruiter through principal-level probing.</p>
      </DisclosureSection>

      <DisclosureSection title="Metric units & taxonomies" defaultOpen={false}>
        <p className={styles.helper}>Customize allowed metric units, skill groups, and readiness scoring weights for non-engineering careers.</p>
      </DisclosureSection>

      <DisclosureSection title="Autosave & drafts" defaultOpen={false}>
        <p className={styles.helper}>Accomplishment edits autosave locally and sync to the API when connected. Unsaved changes are protected before navigation.</p>
      </DisclosureSection>
    </div>
  );
}
