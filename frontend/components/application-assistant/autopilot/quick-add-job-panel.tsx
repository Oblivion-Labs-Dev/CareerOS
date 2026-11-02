"use client";

import React, { useMemo, useState } from "react";
import { enqueueJobsForAutopilot, type EnqueueResult } from "@/lib/application-assistant-api";
import styles from "./autopilot-ui.module.css";

type TailoringMode = "off" | "honest" | "aggressive";

/**
 * Queue postings from their links alone.
 *
 * This used to demand a company and a job title alongside the URL, which was
 * busywork twice over: the posting already states both, and a company typed
 * differently from the board's own slug defeats the duplicate guard, which
 * matches on company + title + URL. People also collect job links in bulk — a
 * dozen open tabs — so the box takes as many as you paste and reports what
 * happened to each one, rather than making you add them one at a time.
 */
export function QuickAddJobPanel({ onAdded }: { onAdded?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [links, setLinks] = useState("");
  const [tailoringMode, setTailoringMode] = useState<TailoringMode>("off");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<EnqueueResult[] | null>(null);

  // Count what will actually be sent, so the button can say how many and the
  // person can see a malformed paste before they submit it.
  const urls = useMemo(
    () =>
      Array.from(
        new Set(
          links
            .split(/[\s,]+/)
            .map((part) => part.trim())
            .filter((part) => /^https?:\/\//i.test(part)),
        ),
      ),
    [links],
  );

  const handleSubmit = async () => {
    if (urls.length === 0) {
      setError("Paste one or more job links (they need to start with http:// or https://).");
      return;
    }
    setSubmitting(true);
    setError(null);
    setResults(null);
    try {
      const res = await enqueueJobsForAutopilot(urls, tailoringMode);
      setResults(res.results || []);
      if ((res.queued ?? 0) > 0) {
        setLinks("");
        onAdded?.();
      }
    } catch (err: any) {
      setError(err?.message || "Could not queue those links.");
    } finally {
      setSubmitting(false);
    }
  };

  const queued = results?.filter((r) => r.state === "queued").length ?? 0;

  return (
    <div className={styles.quickAdd}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={styles.quickAddToggle}
        aria-expanded={expanded}
        aria-controls="quick-add-body"
      >
        <span className={styles.quickAddToggleLabel}>
          <span className={styles.quickAddTogglePlus} aria-hidden="true">
            +
          </span>
          Add jobs by URL
        </span>
        <span className={styles.quickAddChevron} aria-hidden="true">
          ▾
        </span>
      </button>

      {/* The body stays mounted and is revealed by animating the row track from
          0fr to 1fr. Unmounting it on collapse, as this did before, makes a
          transition impossible - there is nothing to transition from - and the
          panel snapped open. Animating the track also means no magic pixel
          height has to be guessed for content that changes size. */}
      <div className={styles.quickAddReveal} data-open={expanded} id="quick-add-body">
        <div className={styles.quickAddRevealInner}>
        <div className={styles.quickAddBody}>
          <p className={styles.quickAddHint}>
            Paste job links — one per line, as many as you like. The company, role and location
            are read from each posting, so there is nothing else to fill in.
          </p>

          <div className={styles.quickAddField}>
            <label className={styles.filterLabel} htmlFor="quick-add-links">
              Job links
            </label>
            <textarea
              id="quick-add-links"
              value={links}
              onChange={(e) => setLinks(e.target.value)}
              rows={5}
              spellCheck={false}
              placeholder={
                "https://job-boards.greenhouse.io/company/jobs/12345\nhttps://jobs.lever.co/company/abc-def\nhttps://jobs.ashbyhq.com/company/uuid"
              }
              className={styles.quickAddTextarea}
            />
            <span className={styles.quickAddCount}>
              {urls.length === 0
                ? "No links yet"
                : `${urls.length} link${urls.length === 1 ? "" : "s"} ready`}
            </span>
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
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting || urls.length === 0}
              className={styles.quickAddSubmit}
            >
              {submitting
                ? `Reading ${urls.length} posting${urls.length === 1 ? "" : "s"}…`
                : `Add ${urls.length || ""} to Queue`.replace("  ", " ")}
            </button>
          </div>

          {error && <div className={styles.quickAddMessageError}>{error}</div>}

          {results && (
            <div className={styles.quickAddResults}>
              <div className={queued > 0 ? styles.quickAddMessageSuccess : styles.quickAddMessageError}>
                {queued} of {results.length} queued.
              </div>
              <ul className={styles.quickAddResultList}>
                {results.map((r) => (
                  <li key={r.url} className={styles.quickAddResultRow} data-state={r.state}>
                    <span className={styles.quickAddResultState}>{r.state}</span>
                    <span className={styles.quickAddResultName}>
                      {r.company || r.title ? `${r.company}${r.company && r.title ? " — " : ""}${r.title}` : r.url}
                    </span>
                    {r.message && <span className={styles.quickAddResultNote}>{r.message}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        </div>
      </div>
    </div>
  );
}
