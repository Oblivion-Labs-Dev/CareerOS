"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl, postJson } from "@/lib/api";

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

export function ReferralsManager() {
  const [referrals, setReferrals] = useState<ReferralContact[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/referrals`, { cache: "no-store" });
      if (!res.ok) throw new Error("Could not load referrals");
      const data = (await res.json()) as { referrals: ReferralContact[] };
      setReferrals(data.referrals || []);
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

  return (
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
  );
}
