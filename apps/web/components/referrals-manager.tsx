"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl, postJson } from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";

export interface ReferralContact {
  id: string;
  contactName: string;
  email?: string;
  linkedin?: string;
  companyName?: string;
  roleTitle?: string;
  phone?: string;
  relationship?: string;
  status?: "active" | "asked" | "referred" | "inactive";
  notes?: string;
}

const EMPTY_FORM = {
  contactName: "",
  email: "",
  linkedin: "",
  companyName: "",
  roleTitle: "",
  phone: "",
  relationship: "",
  status: "active" as const,
  notes: "",
};

const DEFAULT_REFERRAL_ASK_MESSAGE = `I hope you're doing well! I came across a job that aligns closely with my background and was wondering if you'd be open to referring me. I have 7+ years of experience at Microsoft and Amazon building distributed systems, AI infrastructure, and cloud-native platforms, and I've recently been focused on agentic AI and developer tooling.

I believe my experience is a strong match for the role. If you're comfortable referring me, I'd really appreciate it. I've attached the job link and my resume for context. Thanks for taking the time to consider my request!`;

export function ReferralsManager() {
  const [referrals, setReferrals] = useState<ReferralContact[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [askMessage, setAskMessage] = useState(DEFAULT_REFERRAL_ASK_MESSAGE);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingMessage, setSavingMessage] = useState(false);
  const [messageCopied, setMessageCopied] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const base = getClientApiBaseUrl();
      const [referralsRes, messageRes] = await Promise.all([
        fetch(`${base}/referrals`, { cache: "no-store" }),
        fetch(`${base}/referrals/ask-message`, { cache: "no-store" }),
      ]);
      if (!referralsRes.ok) throw new Error("Could not load referrals");
      const referralsData = (await referralsRes.json()) as { referrals: ReferralContact[] };
      setReferrals(referralsData.referrals || []);
      if (messageRes.ok) {
        const messageData = (await messageRes.json()) as { message?: string };
        if (messageData.message?.trim()) {
          setAskMessage(messageData.message);
        }
      }
    } catch {
      setError("Backend offline — start the API to save referral contacts.");
      setReferrals([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!form.contactName.trim()) return;
    setSaving(true);
    setError("");
    try {
      await postJson("/referrals", {
        referral: {
          ...form,
          contactName: form.contactName.trim(),
        },
      });
      setForm(EMPTY_FORM);
      await load();
    } catch {
      setError("Could not save referral contact.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await postJson(`/referrals/${id}`, {}, "DELETE");
      setReferrals((items) => items.filter((item) => item.id !== id));
    } catch {
      setError("Could not delete referral contact.");
    }
  }

  async function handleSaveMessage() {
    if (!askMessage.trim()) return;
    setSavingMessage(true);
    setError("");
    try {
      await postJson("/referrals/ask-message", { message: askMessage }, "PUT");
    } catch {
      setError("Could not save referral message.");
    } finally {
      setSavingMessage(false);
    }
  }

  async function handleCopyMessage() {
    const ok = await copyTextToClipboard(askMessage);
    if (!ok) {
      setError("Could not copy message to clipboard.");
      return;
    }
    setMessageCopied(true);
    window.setTimeout(() => setMessageCopied(false), 2000);
  }

  return (
    <div className="referrals-page">
      <article className="workflow-panel referral-message-panel">
        <div className="referral-message-header">
          <div>
            <span className="toc-card-kicker">Referral ask</span>
            <h2>Outreach message</h2>
            <p className="muted">Saved template for LinkedIn or email when you ask someone for a referral.</p>
          </div>
          <div className="referral-message-actions">
            <button
              type="button"
              className={`btn-secondary referral-copy-btn${messageCopied ? " referral-copy-btn--copied" : ""}`}
              onClick={() => void handleCopyMessage()}
            >
              {messageCopied ? "Copied!" : "Copy message"}
            </button>
            <button type="button" className="btn-primary" disabled={savingMessage} onClick={() => void handleSaveMessage()}>
              {savingMessage ? "Saving…" : "Save message"}
            </button>
          </div>
        </div>
        <textarea
          className="referral-message-textarea"
          value={askMessage}
          onChange={(e) => setAskMessage(e.target.value)}
          rows={8}
          spellCheck
        />
      </article>

      <div className="referrals-layout">
      <article className="workflow-panel">
        <span className="toc-card-kicker">Add referral contact</span>
        <h2>Someone who can refer you</h2>
        <p className="muted" style={{ marginBottom: "1rem" }}>
          Track people at target companies — hiring managers, alumni, recruiters, or warm connections.
        </p>
        <form className="referral-form" onSubmit={handleSubmit}>
          <div className="referral-form-grid">
            <label>
              Name *
              <input
                value={form.contactName}
                onChange={(e) => setForm({ ...form, contactName: e.target.value })}
                placeholder="Alex Rivera"
                required
              />
            </label>
            <label>
              Company
              <input
                value={form.companyName}
                onChange={(e) => setForm({ ...form, companyName: e.target.value })}
                placeholder="Microsoft"
              />
            </label>
            <label>
              Email
              <input
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="alex@company.com"
              />
            </label>
            <label>
              LinkedIn
              <input
                value={form.linkedin}
                onChange={(e) => setForm({ ...form, linkedin: e.target.value })}
                placeholder="https://linkedin.com/in/..."
              />
            </label>
            <label>
              Role / title
              <input
                value={form.roleTitle}
                onChange={(e) => setForm({ ...form, roleTitle: e.target.value })}
                placeholder="Engineering Manager"
              />
            </label>
            <label>
              Phone
              <input
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                placeholder="+1 (555) 000-0000"
              />
            </label>
            <label>
              Relationship
              <input
                value={form.relationship}
                onChange={(e) => setForm({ ...form, relationship: e.target.value })}
                placeholder="Former colleague, alumni, recruiter"
              />
            </label>
            <label>
              Status
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as typeof form.status })}>
                <option value="active">Active</option>
                <option value="asked">Asked</option>
                <option value="referred">Referred</option>
                <option value="inactive">Inactive</option>
              </select>
            </label>
          </div>
          <label>
            Notes
            <textarea
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              placeholder="Which roles they can refer for, last conversation, intro path…"
              rows={3}
            />
          </label>
          {error ? <p className="referral-error">{error}</p> : null}
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? "Saving…" : "Add contact"}
          </button>
        </form>
      </article>

      <article className="workflow-panel dashboard-panel--wide">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Referral network</span>
            <h2>{loading ? "Loading…" : `${referrals.length} contacts`}</h2>
          </div>
        </div>
        {referrals.length ? (
          <div className="dashboard-list">
            {referrals.map((item) => (
              <div className="dashboard-list-row referral-row" key={item.id}>
                <div>
                  <h3>{item.contactName}</h3>
                  <span>
                    {[item.companyName, item.roleTitle, item.relationship].filter(Boolean).join(" · ") || "No company set"}
                  </span>
                  <div className="referral-links">
                    {item.email ? <a href={`mailto:${item.email}`}>{item.email}</a> : null}
                    {item.linkedin ? (
                      <a href={item.linkedin} target="_blank" rel="noreferrer">
                        LinkedIn
                      </a>
                    ) : null}
                    {item.phone ? <span>{item.phone}</span> : null}
                  </div>
                  {item.notes ? <p className="referral-notes">{item.notes}</p> : null}
                </div>
                <div className="referral-row-actions">
                  <span className="referral-status">{item.status || "active"}</span>
                  <button type="button" className="btn-ghost" onClick={() => void handleDelete(item.id)}>
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted dashboard-empty">
            {loading ? "Loading referral contacts…" : "No referral contacts yet. Add someone who can refer you at a target company."}
          </p>
        )}
      </article>
      </div>
    </div>
  );
}
