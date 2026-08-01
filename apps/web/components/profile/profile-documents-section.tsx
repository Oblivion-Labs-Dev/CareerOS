"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchDefaultResume, parseResumeIntoProfile, uploadDefaultResume, type StoredResume } from "@/lib/documents-api";

type Props = {
  onProfileSynced?: () => void;
};

export function ProfileDocumentsSection({ onProfileSynced }: Props) {
  const [resume, setResume] = useState<StoredResume | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setResume(await fetchDefaultResume());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load documents");
      setResume(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleUpload = async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    setError("");
    setMessage("");
    try {
      const saved = await uploadDefaultResume(file);
      setResume(saved);
      setMessage(`Uploaded ${saved.name || file.name}. Sync to profile to fill contact fields and improve job matching.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleSyncProfile = async () => {
    if (!resume) return;
    setSyncing(true);
    setError("");
    setMessage("");
    try {
      const result = await parseResumeIntoProfile(true);
      const extracted = Object.keys(result.extracted || {});
      setMessage(
        extracted.length
          ? `Profile updated from resume: ${extracted.join(", ")}.`
          : "Profile already has the main fields from your resume.",
      );
      onProfileSynced?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sync resume to profile");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <section className="workflow-panel dashboard-panel--wide profile-documents-section" id="documents" aria-label="Documents">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Documents</span>
          <h2>Default resume</h2>
          <p className="muted" style={{ marginTop: "0.35rem" }}>
            Your uploaded resume powers job fit scoring, AI Assistant prep, and application autofill.
          </p>
        </div>
      </div>

      {loading ? (
        <p className="muted dashboard-empty" role="status">
          Loading documents…
        </p>
      ) : (
        <>
          <div className="profile-documents-grid">
            <div className="profile-documents-upload">
              <label className="profile-documents-dropzone">
                <input
                  type="file"
                  accept=".pdf,.txt,.doc,.docx"
                  disabled={uploading}
                  onChange={(e) => void handleUpload(e.target.files?.[0] || null)}
                />
                <strong>{uploading ? "Uploading…" : "Upload resume"}</strong>
                <span className="muted">PDF, DOCX, DOC, or TXT</span>
              </label>
              {resume?.name ? (
                <div className="profile-documents-current">
                  <span className="toc-card-kicker">Current file</span>
                  <p>
                    <strong>{resume.name}</strong>
                    {resume.updatedAt ? <span className="muted"> · Updated {new Date(resume.updatedAt).toLocaleString()}</span> : null}
                  </p>
                  <button type="button" className="btn btn-sm" onClick={() => void handleSyncProfile()} disabled={syncing}>
                    {syncing ? "Syncing…" : "Sync to profile"}
                  </button>
                </div>
              ) : (
                <p className="muted dashboard-empty">No resume uploaded yet. Add one to improve match scores and autofill.</p>
              )}
            </div>

            <aside className="profile-documents-notes">
              <span className="toc-card-kicker">Used for</span>
              <ul className="profile-documents-list">
                <li>Job Scraper relevancy and fit scores</li>
                <li>AI Assistant field prep and missing-field checks</li>
                <li>Resume scan and accomplishment extraction below</li>
              </ul>
            </aside>
          </div>

          {error ? (
            <p className="profile-documents-message profile-documents-message--error" role="alert">
              {error}
            </p>
          ) : null}
          {message ? (
            <p className="profile-documents-message profile-documents-message--ok" role="status">
              {message}
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}
