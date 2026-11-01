"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { WorkflowPage } from "@/components/scaffold-page";
import {
  addMemoryNote,
  deleteMemoryNote,
  getPortfolioSettings,
  listMemoryNotes,
  savePortfolioSettings,
  type MemoryNote,
  type PortfolioSettings,
} from "@/lib/settings-api";
import { getSettings, updateSettings } from "@/lib/application-assistant-api";

type BlacklistedCompany = { company: string; reason: string };

export default function SettingsPage() {
  const [notes, setNotes] = useState<MemoryNote[]>([]);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);

  const [portfolio, setPortfolio] = useState<PortfolioSettings>({ isPublic: false, slug: "" });
  const [portfolioBusy, setPortfolioBusy] = useState(false);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [portfolioLoaded, setPortfolioLoaded] = useState(false);

  const [blacklist, setBlacklist] = useState<BlacklistedCompany[]>([]);
  const [blacklistCompanyDraft, setBlacklistCompanyDraft] = useState("");
  const [blacklistReasonDraft, setBlacklistReasonDraft] = useState("");
  const [blacklistBusy, setBlacklistBusy] = useState(false);
  const [blacklistError, setBlacklistError] = useState<string | null>(null);

  useEffect(() => {
    void listMemoryNotes()
      .then(setNotes)
      .catch((err) => {
        console.warn("[settings] memory notes failed to load", err);
        setNotesError("Could not load saved preferences.");
      });
    void getPortfolioSettings()
      .then((cfg) => {
        setPortfolio(cfg);
        setPortfolioLoaded(true);
      })
      .catch((err) => {
        console.warn("[settings] portfolio settings failed to load", err);
        setPortfolioError("Could not load portfolio settings.");
        setPortfolioLoaded(true);
      });
    void getSettings()
      .then((res) => setBlacklist(Array.isArray(res.settings?.companyBlacklist) ? res.settings.companyBlacklist : []))
      .catch((err) => {
        console.warn("[settings] company blacklist failed to load", err);
        setBlacklistError("Could not load blocked companies.");
      });
  }, []);

  async function handleAddBlacklistedCompany() {
    const company = blacklistCompanyDraft.trim();
    if (!company) return;
    setBlacklistBusy(true);
    setBlacklistError(null);
    const next = [...blacklist, { company, reason: blacklistReasonDraft.trim() }];
    try {
      const res = await updateSettings({ companyBlacklist: next });
      setBlacklist(Array.isArray(res.settings?.companyBlacklist) ? res.settings.companyBlacklist : next);
      setBlacklistCompanyDraft("");
      setBlacklistReasonDraft("");
    } catch {
      setBlacklistError("Could not save that company — it may not be blocked yet.");
    } finally {
      setBlacklistBusy(false);
    }
  }

  async function handleRemoveBlacklistedCompany(company: string) {
    const previous = blacklist;
    const next = blacklist.filter((entry) => entry.company !== company);
    setBlacklist(next);
    try {
      await updateSettings({ companyBlacklist: next });
    } catch {
      setBlacklistError("Could not remove that company — it may still be blocked.");
      setBlacklist(previous);
    }
  }

  async function handleAddNote() {
    const text = noteDraft.trim();
    if (!text) return;
    setNoteBusy(true);
    setNotesError(null);
    try {
      const note = await addMemoryNote(text);
      setNotes((prev) => [note, ...prev]);
      setNoteDraft("");
    } catch {
      setNotesError("Could not save that note.");
    } finally {
      setNoteBusy(false);
    }
  }

  async function handleDeleteNote(id: string) {
    setNotes((prev) => prev.filter((n) => n.id !== id));
    try {
      await deleteMemoryNote(id);
    } catch {
      setNotesError("Could not delete that note — it may still be listed.");
      void listMemoryNotes().then(setNotes).catch(() => undefined);
    }
  }

  async function handleSavePortfolio(patch: Partial<PortfolioSettings>) {
    setPortfolioBusy(true);
    setPortfolioError(null);
    try {
      const updated = await savePortfolioSettings({ ...portfolio, ...patch });
      setPortfolio(updated);
    } catch (err) {
      setPortfolioError(err instanceof Error ? err.message : "Could not save portfolio settings.");
    } finally {
      setPortfolioBusy(false);
    }
  }

  const publicUrl = portfolio.slug && typeof window !== "undefined" ? `${window.location.origin}/u/${portfolio.slug}` : "";

  return (
    <WorkflowPage
      title="Settings"
      eyebrow="Settings"
      subtitle="What the assistant remembers, companies Autopilot skips, and your public portfolio."
      primaryAction={{ href: "/profile", label: "Tailoring & profile" }}
      outcomes={[]}
      focusAreas={[]}
    >

    <section className="dashboard-panel" aria-labelledby="assistant-memory">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Trust</span>
          <h2 id="assistant-memory">What I remember</h2>
          <p className="muted dashboard-panel-copy">
            Standing preferences you&apos;ve told the assistant to keep in mind — used when it tailors your resume for a
            specific job (see <Link href="/profile">Profile</Link>). They can guide style and format, never override the
            rule that it only writes from evidence you&apos;ve actually supplied.
          </p>
        </div>
      </div>
      <div style={{ display: "flex", gap: "var(--cos-space-3, 0.75rem)", marginBottom: "var(--cos-space-4, 1rem)" }}>
        <input
          type="text"
          value={noteDraft}
          onChange={(e) => setNoteDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void handleAddNote(); }}
          placeholder="e.g. Always keep my resume to one page"
          style={{
            flex: 1,
            padding: "10px 12px",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm, 10px)",
            color: "var(--text)",
            font: "inherit",
          }}
        />
        <button type="button" className="btn-primary btn-sm" disabled={noteBusy || !noteDraft.trim()} onClick={() => void handleAddNote()}>
          {noteBusy ? "Saving…" : "Add"}
        </button>
      </div>
      {notesError ? <p style={{ color: "var(--risk, #e6897c)", fontSize: "var(--cos-text-xs, 0.72rem)" }}>{notesError}</p> : null}
      {notes.length === 0 ? (
        <p className="muted dashboard-panel-copy">Nothing saved yet — add a preference above.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "8px" }}>
          {notes.map((note) => (
            <li
              key={note.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "var(--cos-space-3, 0.75rem)",
                padding: "10px 12px",
                background: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm, 10px)",
              }}
            >
              <span style={{ color: "var(--text)" }}>{note.text}</span>
              <button type="button" className="btn-secondary btn-sm" onClick={() => void handleDeleteNote(note.id)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>

    <section className="dashboard-panel" aria-labelledby="company-blacklist">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Trust</span>
          <h2 id="company-blacklist">Do-not-apply companies</h2>
          <p className="muted dashboard-panel-copy">
            Companies you never want Autopilot to apply to again. Anything already queued there is filed Ineligible on
            the next run — remove a company here to let it back in.
          </p>
        </div>
      </div>
      <div style={{ display: "flex", gap: "var(--cos-space-3, 0.75rem)", marginBottom: "var(--cos-space-4, 1rem)", flexWrap: "wrap" }}>
        <input
          type="text"
          value={blacklistCompanyDraft}
          onChange={(e) => setBlacklistCompanyDraft(e.target.value)}
          placeholder="Company name"
          style={{
            flex: "1 1 200px",
            padding: "10px 12px",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm, 10px)",
            color: "var(--text)",
            font: "inherit",
          }}
        />
        <input
          type="text"
          value={blacklistReasonDraft}
          onChange={(e) => setBlacklistReasonDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void handleAddBlacklistedCompany(); }}
          placeholder="Reason (optional)"
          style={{
            flex: "2 1 260px",
            padding: "10px 12px",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm, 10px)",
            color: "var(--text)",
            font: "inherit",
          }}
        />
        <button
          type="button"
          className="btn-primary btn-sm"
          disabled={blacklistBusy || !blacklistCompanyDraft.trim()}
          onClick={() => void handleAddBlacklistedCompany()}
        >
          {blacklistBusy ? "Saving…" : "Add"}
        </button>
      </div>
      {blacklistError ? <p style={{ color: "var(--risk, #e6897c)", fontSize: "var(--cos-text-xs, 0.72rem)" }}>{blacklistError}</p> : null}
      {blacklist.length === 0 ? (
        <p className="muted dashboard-panel-copy">No companies blocked yet.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "8px" }}>
          {blacklist.map((entry) => (
            <li
              key={entry.company}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "var(--cos-space-3, 0.75rem)",
                padding: "10px 12px",
                background: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm, 10px)",
              }}
            >
              <span style={{ color: "var(--text)" }}>
                <strong>{entry.company}</strong>
                {entry.reason ? <span className="muted"> — {entry.reason}</span> : null}
              </span>
              <button type="button" className="btn-secondary btn-sm" onClick={() => void handleRemoveBlacklistedCompany(entry.company)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>

    <section className="dashboard-panel" aria-labelledby="public-portfolio">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Share</span>
          <h2 id="public-portfolio">Public portfolio</h2>
          <p className="muted dashboard-panel-copy">
            A read-only page recruiters can view — name, headline, top skills, and a few accomplishment summaries. No
            email, phone, or demographic answers are ever included.
          </p>
        </div>
      </div>
      {portfolioLoaded ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--cos-space-3, 0.75rem)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--cos-space-3, 0.75rem)", flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--text)" }}>
              <input
                type="checkbox"
                checked={portfolio.isPublic}
                disabled={portfolioBusy}
                onChange={(e) => void handleSavePortfolio({ isPublic: e.target.checked })}
              />
              Make my portfolio public
            </label>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--cos-space-3, 0.75rem)", flexWrap: "wrap" }}>
            <input
              type="text"
              value={portfolio.slug}
              onChange={(e) => setPortfolio((p) => ({ ...p, slug: e.target.value }))}
              onBlur={() => void handleSavePortfolio({ slug: portfolio.slug })}
              placeholder="your-name"
              style={{
                padding: "10px 12px",
                background: "var(--bg)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm, 10px)",
                color: "var(--text)",
                font: "inherit",
                minWidth: "220px",
              }}
            />
            {publicUrl ? (
              <>
                <code style={{ color: "var(--text-secondary)", fontSize: "var(--cos-text-xs, 0.72rem)" }}>{publicUrl}</code>
                {portfolio.isPublic ? (
                  <Link href={`/u/${portfolio.slug}`} target="_blank" className="btn-secondary btn-sm">View</Link>
                ) : null}
              </>
            ) : null}
          </div>
          {portfolioError ? <p style={{ color: "var(--risk, #e6897c)", fontSize: "var(--cos-text-xs, 0.72rem)" }}>{portfolioError}</p> : null}
        </div>
      ) : (
        <p className="muted dashboard-panel-copy">Loading…</p>
      )}
    </section>
    </WorkflowPage>
  );
}
