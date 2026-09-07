"use client";

import React, { useState } from "react";
import { enqueueJobForAutopilot } from "@/lib/application-assistant-api";
import styles from "./autopilot-ui.module.css";

type TailoringMode = "off" | "honest" | "aggressive";

export function QuickAddJobPanel({ onAdded }: { onAdded?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [applicationUrl, setApplicationUrl] = useState("");
  const [tailoringMode, setTailoringMode] = useState<TailoringMode>("honest");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  const reset = () => {
    setCompany("");
    setTitle("");
    setLocation("");
    setApplicationUrl("");
    setTailoringMode("honest");
  };

  const handleSubmit = async () => {
    if (!company.trim() || !title.trim() || !applicationUrl.trim()) {
      setMessage({ tone: "error", text: "Company, title, and application URL are all required." });
      return;
    }
    setSubmitting(true);
    setMessage(null);
    try {
      const res = await enqueueJobForAutopilot({
        company: company.trim(),
        title: title.trim(),
        location: location.trim(),
        applicationUrl: applicationUrl.trim(),
        tailoringMode,
      });
      if (res.success === false || (res as any).filtered) {
        setMessage({ tone: "error", text: (res as any).message || "This job didn't pass the hard filters (role, sponsorship, or location) and was not queued." });
      } else if ((res as any).deduplicated) {
        setMessage({ tone: "error", text: (res as any).message || "This job is already in the system." });
      } else {
        setMessage({ tone: "success", text: `Queued "${title.trim()}" at ${company.trim()} (${tailoringMode} tailoring). It'll show up below in Autopilot.` });
        reset();
        onAdded?.();
      }
    } catch (err: any) {
      setMessage({ tone: "error", text: err?.message || "Failed to queue this job." });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.quickAdd}>
      <button type="button" onClick={() => setExpanded((v) => !v)} className={styles.quickAddToggle}>
        <span className={styles.quickAddToggleLabel}>
          <span className={styles.quickAddTogglePlus}>+</span>
          Add job by URL
        </span>
        <span className={styles.quickAddChevron}>{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className={styles.quickAddBody}>
          <p className={styles.quickAddHint}>
            Paste a specific job posting to queue it for Autopilot with a chosen resume-tailoring mode, instead of waiting for the next discovery scrape.
          </p>
          <div className={styles.quickAddGrid}>
            <div className={styles.quickAddField}>
              <label className={styles.filterLabel}>Company</label>
              <input
                type="text"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                placeholder="e.g. Stripe"
                className={styles.quickAddInput}
              />
            </div>
            <div className={styles.quickAddField}>
              <label className={styles.filterLabel}>Job Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Senior Software Engineer"
                className={styles.quickAddInput}
              />
            </div>
          </div>
          <div className={styles.quickAddField}>
            <label className={styles.filterLabel}>Location (optional)</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Remote, or San Francisco, CA"
              className={styles.quickAddInput}
            />
          </div>
          <div className={styles.quickAddField}>
            <label className={styles.filterLabel}>Application URL</label>
            <input
              type="text"
              value={applicationUrl}
              onChange={(e) => setApplicationUrl(e.target.value)}
              placeholder="https://job-boards.greenhouse.io/company/jobs/12345"
              className={styles.quickAddInput}
            />
          </div>
          <div className={styles.quickAddModeRow}>
            <div className={styles.quickAddField}>
              <label className={styles.filterLabel}>Resume Tailoring</label>
              <div className={styles.quickAddModeGroup}>
                {(["off", "honest", "aggressive"] as TailoringMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setTailoringMode(mode)}
                    className={`${styles.modeToggle} ${tailoringMode === mode ? styles.modeToggleActive : ""}`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </div>
            <button type="button" onClick={handleSubmit} disabled={submitting} className={styles.quickAddSubmit}>
              {submitting ? "Queuing..." : "Add to Queue"}
            </button>
          </div>
          {message && (
            <div className={message.tone === "success" ? styles.quickAddMessageSuccess : styles.quickAddMessageError}>
              {message.text}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
