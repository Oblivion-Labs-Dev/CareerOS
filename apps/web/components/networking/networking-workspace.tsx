"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  addCompanyContact,
  draftOutreach,
  getCompanyWorkspace,
  listNetworkingCompanies,
  type CompanyWorkspace,
  type NetworkingContact,
  type OutreachDraft,
} from "@/lib/networking-api";

const STATUS_COLOR: Record<string, string> = {
  active: "#2ee8c9",
  asked: "#f59e0b",
  referred: "#34d399",
  inactive: "#94a3b8",
};

const EMPTY_CONTACT_FORM = {
  contactName: "",
  roleTitle: "",
  email: "",
  linkedin: "",
  relationship: "",
  notes: "",
};

function StatusPill({ status }: { status?: string }) {
  const key = status || "active";
  const color = STATUS_COLOR[key] || STATUS_COLOR.active;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: "0.03em",
        textTransform: "uppercase",
        color,
        border: `1px solid ${color}66`,
        background: `${color}1a`,
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: 999, background: color }} />
      {key}
    </span>
  );
}

function OutreachPanel({
  contact,
  companyName,
  jobId,
  onClose,
}: {
  contact: NetworkingContact;
  companyName: string;
  jobId?: string;
  onClose: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<OutreachDraft | null>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    draftOutreach({
      contactName: contact.contactName,
      contactRole: contact.roleTitle,
      companyName,
      jobId,
    })
      .then((res) => {
        if (!cancelled) setDraft(res.draft);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not draft outreach.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [contact.contactName, contact.roleTitle, companyName, jobId]);

  async function copy(field: string, text: string) {
    const ok = await copyTextToClipboard(text);
    if (ok) {
      setCopiedField(field);
      window.setTimeout(() => setCopiedField((f) => (f === field ? null : f)), 1800);
    }
  }

  return (
    <div
      style={{
        marginTop: 12,
        padding: "var(--cos-space-4, 1rem)",
        background: "var(--bg)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md, 14px)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <strong style={{ fontSize: 13 }}>Outreach draft for {contact.contactName}</strong>
        <button type="button" className="btn-ghost" onClick={onClose}>
          Close
        </button>
      </div>
      {loading ? <p className="muted">Drafting with your resume/profile as context…</p> : null}
      {error ? (
        <p style={{ color: "#f43f5e", fontSize: 13 }}>{error}</p>
      ) : null}
      {draft ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span className="toc-card-kicker">Email subject</span>
              <button type="button" className="btn-secondary btn-sm" onClick={() => void copy("subject", draft.emailSubject)}>
                {copiedField === "subject" ? "Copied!" : "Copy"}
              </button>
            </div>
            <p style={{ fontSize: 14 }}>{draft.emailSubject}</p>
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span className="toc-card-kicker">Email body</span>
              <button type="button" className="btn-secondary btn-sm" onClick={() => void copy("body", draft.emailBody)}>
                {copiedField === "body" ? "Copied!" : "Copy"}
              </button>
            </div>
            <p style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>{draft.emailBody}</p>
          </div>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
              <span className="toc-card-kicker">LinkedIn connection note</span>
              <button type="button" className="btn-secondary btn-sm" onClick={() => void copy("linkedin", draft.linkedinNote)}>
                {copiedField === "linkedin" ? "Copied!" : "Copy"}
              </button>
            </div>
            <p style={{ fontSize: 14 }}>{draft.linkedinNote}</p>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>
            Nothing is sent automatically — copy whichever you want and send it yourself, editing as needed.
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function NetworkingWorkspace() {
  const [companies, setCompanies] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [newCompany, setNewCompany] = useState("");
  const [workspace, setWorkspace] = useState<CompanyWorkspace | null>(null);
  const [loadingCompanies, setLoadingCompanies] = useState(true);
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contactForm, setContactForm] = useState(EMPTY_CONTACT_FORM);
  const [savingContact, setSavingContact] = useState(false);
  const [outreachTarget, setOutreachTarget] = useState<string | null>(null);

  const loadCompanies = useCallback(async () => {
    setLoadingCompanies(true);
    try {
      const res = await listNetworkingCompanies();
      setCompanies(res.companies);
      setSelected((current) => current ?? res.companies[0] ?? null);
    } catch {
      setError("Backend offline — start the API to load your network.");
    } finally {
      setLoadingCompanies(false);
    }
  }, []);

  useEffect(() => {
    void loadCompanies();
  }, [loadCompanies]);

  const loadWorkspace = useCallback(async (company: string) => {
    setLoadingWorkspace(true);
    setError(null);
    setOutreachTarget(null);
    try {
      const res = await getCompanyWorkspace(company);
      setWorkspace(res);
    } catch {
      setError(`Could not load ${company}.`);
      setWorkspace(null);
    } finally {
      setLoadingWorkspace(false);
    }
  }, []);

  useEffect(() => {
    if (selected) void loadWorkspace(selected);
  }, [selected, loadWorkspace]);

  async function handleAddContact(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !contactForm.contactName.trim()) return;
    setSavingContact(true);
    try {
      await addCompanyContact(selected, {
        ...contactForm,
        contactName: contactForm.contactName.trim(),
      });
      setContactForm(EMPTY_CONTACT_FORM);
      await loadWorkspace(selected);
    } catch {
      setError("Could not save that contact.");
    } finally {
      setSavingContact(false);
    }
  }

  function handleAddCompany(event: React.FormEvent) {
    event.preventDefault();
    const name = newCompany.trim();
    if (!name) return;
    setCompanies((current) => (current.includes(name) ? current : [...current, name].sort((a, b) => a.localeCompare(b))));
    setSelected(name);
    setNewCompany("");
  }

  const latestJobId = useMemo(() => workspace?.discoveredJobs?.[0]?.id, [workspace]);

  return (
    <div className="networking-page" style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: "var(--cos-space-4, 1rem)" }}>
      <article className="workflow-panel">
        <span className="toc-card-kicker">Companies</span>
        <h2 style={{ fontSize: 16 }}>{loadingCompanies ? "Loading…" : `${companies.length} tracked`}</h2>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 12, maxHeight: 420, overflowY: "auto" }}>
          {companies.map((company) => (
            <button
              key={company}
              type="button"
              onClick={() => setSelected(company)}
              style={{
                textAlign: "left",
                padding: "8px 10px",
                borderRadius: "var(--radius-sm, 10px)",
                border: "1px solid transparent",
                background: selected === company ? "var(--card-hover, var(--card))" : "transparent",
                borderColor: selected === company ? "var(--accent)" : "transparent",
                color: "var(--text)",
                cursor: "pointer",
                font: "inherit",
              }}
            >
              {company}
            </button>
          ))}
          {!loadingCompanies && companies.length === 0 ? (
            <p className="muted" style={{ fontSize: 13 }}>
              No companies yet — apply to a role, or add one below to start a workspace for someone you already know.
            </p>
          ) : null}
        </div>
        <form onSubmit={handleAddCompany} style={{ marginTop: 12, display: "flex", gap: 6 }}>
          <input
            value={newCompany}
            onChange={(e) => setNewCompany(e.target.value)}
            placeholder="Add a company"
            style={{
              flex: 1,
              padding: "8px 10px",
              background: "var(--bg)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm, 10px)",
              color: "var(--text)",
              font: "inherit",
            }}
          />
          <button type="submit" className="btn-secondary btn-sm">
            Add
          </button>
        </form>
      </article>

      <article className="workflow-panel dashboard-panel--wide">
        {error ? <p style={{ color: "#f43f5e", marginBottom: 12 }}>{error}</p> : null}
        {!selected ? (
          <p className="muted">Pick or add a company on the left to open its workspace.</p>
        ) : loadingWorkspace ? (
          <p className="muted">Loading {selected}…</p>
        ) : (
          <>
            <div className="dashboard-panel-header">
              <div>
                <span className="toc-card-kicker">Workspace</span>
                <h2>{selected}</h2>
                <p className="muted" style={{ fontSize: 13 }}>
                  {(workspace?.applications.length ?? 0) > 0
                    ? `${workspace?.applications.length} application${workspace?.applications.length === 1 ? "" : "s"} tracked here.`
                    : "No applications tracked here yet."}
                </p>
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <span className="toc-card-kicker">Contacts</span>
              {workspace?.contacts.length ? (
                <div className="dashboard-list" style={{ marginTop: 8 }}>
                  {workspace.contacts.map((contact) => (
                    <div className="dashboard-list-row" key={contact.id} style={{ flexDirection: "column", alignItems: "stretch" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                        <div>
                          <h3 style={{ margin: 0 }}>{contact.contactName}</h3>
                          <span className="muted" style={{ fontSize: 13 }}>
                            {[contact.roleTitle, contact.relationship].filter(Boolean).join(" · ") || "No role noted"}
                          </span>
                          <div style={{ display: "flex", gap: 10, marginTop: 4, fontSize: 13 }}>
                            {contact.email ? <a href={`mailto:${contact.email}`}>{contact.email}</a> : null}
                            {contact.linkedin ? (
                              <a href={contact.linkedin} target="_blank" rel="noreferrer">
                                LinkedIn
                              </a>
                            ) : null}
                          </div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                          <StatusPill status={contact.status} />
                          <button
                            type="button"
                            className="btn-primary btn-sm"
                            onClick={() => setOutreachTarget(outreachTarget === contact.id ? null : contact.id)}
                          >
                            {outreachTarget === contact.id ? "Hide draft" : "Draft outreach"}
                          </button>
                        </div>
                      </div>
                      {outreachTarget === contact.id && selected ? (
                        <OutreachPanel
                          contact={contact}
                          companyName={selected}
                          jobId={latestJobId}
                          onClose={() => setOutreachTarget(null)}
                        />
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>
                  No contacts at {selected} yet. We don&apos;t have automated recruiter lookup wired up — add someone you&apos;ve
                  found on LinkedIn or the company&apos;s team page below.
                </p>
              )}
            </div>

            <form onSubmit={handleAddContact} style={{ marginTop: 20 }}>
              <span className="toc-card-kicker">Add a contact</span>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: 8,
                  marginTop: 8,
                }}
              >
                <input
                  value={contactForm.contactName}
                  onChange={(e) => setContactForm({ ...contactForm, contactName: e.target.value })}
                  placeholder="Name *"
                  required
                  style={inputStyle}
                />
                <input
                  value={contactForm.roleTitle}
                  onChange={(e) => setContactForm({ ...contactForm, roleTitle: e.target.value })}
                  placeholder="Role / title"
                  style={inputStyle}
                />
                <input
                  value={contactForm.email}
                  onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
                  placeholder="Email"
                  type="email"
                  style={inputStyle}
                />
                <input
                  value={contactForm.linkedin}
                  onChange={(e) => setContactForm({ ...contactForm, linkedin: e.target.value })}
                  placeholder="LinkedIn URL"
                  style={inputStyle}
                />
                <input
                  value={contactForm.relationship}
                  onChange={(e) => setContactForm({ ...contactForm, relationship: e.target.value })}
                  placeholder="How you know them"
                  style={inputStyle}
                />
              </div>
              <textarea
                value={contactForm.notes}
                onChange={(e) => setContactForm({ ...contactForm, notes: e.target.value })}
                placeholder="Notes — where you found them, last conversation…"
                rows={2}
                style={{ ...inputStyle, width: "100%", marginTop: 8, resize: "vertical" }}
              />
              <button type="submit" className="btn-primary btn-sm" disabled={savingContact} style={{ marginTop: 8 }}>
                {savingContact ? "Saving…" : "Add contact"}
              </button>
            </form>

            {workspace?.discoveredJobs.length ? (
              <div style={{ marginTop: 20 }}>
                <span className="toc-card-kicker">Open roles seen at {selected}</span>
                <p className="muted" style={{ fontSize: 12 }}>
                  From the job scraper — outreach drafts above reference the most recent one for context.
                </p>
              </div>
            ) : null}
          </>
        )}
      </article>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "8px 10px",
  background: "var(--bg)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm, 10px)",
  color: "var(--text)",
  font: "inherit",
};
