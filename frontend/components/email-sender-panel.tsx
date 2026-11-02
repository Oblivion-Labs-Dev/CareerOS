"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl, postJson } from "@/lib/api";

interface RecruiterThread {
  uid: string;
  subject: string;
  fromName: string;
  fromAddress: string;
  date: string;
}

const EMPTY_FORM = {
  to: "",
  subject: "",
  body: "",
};

export function EmailSenderPanel() {
  const [gmailReady, setGmailReady] = useState<boolean | null>(null);
  const [gmailUser, setGmailUser] = useState("");
  const [form, setForm] = useState(EMPTY_FORM);
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [threads, setThreads] = useState<RecruiterThread[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(false);

  const checkGmail = useCallback(async () => {
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/email/verify`, { cache: "no-store" });
      if (!res.ok) throw new Error("Could not verify Gmail");
      const data = (await res.json()) as { success: boolean; configured?: boolean; user?: string };
      if (data.configured === false) {
        setGmailReady(false);
        setGmailUser("");
        return;
      }
      setGmailReady(Boolean(data.success));
      setGmailUser(data.user || "");
    } catch {
      setGmailReady(false);
      setError("Backend offline — start the API on port 8000.");
    }
  }, []);

  const loadThreads = useCallback(async () => {
    setLoadingThreads(true);
    setError("");
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/email/recruiter-threads?limit=8`, { cache: "no-store" });
      if (!res.ok) throw new Error("Could not load recruiter threads");
      const data = (await res.json()) as { threads: RecruiterThread[] };
      setThreads(data.threads || []);
    } catch {
      setThreads([]);
      setError("Could not load recruiter threads. Check Gmail credentials in apps/api/.env.");
    } finally {
      setLoadingThreads(false);
    }
  }, []);

  useEffect(() => {
    void checkGmail();
  }, [checkGmail]);

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    if (!form.to.trim() || !form.subject.trim() || !form.body.trim()) return;

    setSending(true);
    setStatus("");
    setError("");
    try {
      const result = await postJson<{ success: boolean; messageId?: string }>("/email/send", {
        to: form.to.trim(),
        subject: form.subject.trim(),
        text: form.body.trim(),
      });
      setStatus(result.messageId ? `Sent — Message-ID: ${result.messageId}` : "Email sent.");
      setForm(EMPTY_FORM);
    } catch {
      setError("Send failed. Confirm GMAIL_USER and GMAIL_APP_PASSWORD in apps/api/.env.");
    } finally {
      setSending(false);
    }
  }

  function applyThreadReply(thread: RecruiterThread) {
    setForm((current) => ({
      ...current,
      to: thread.fromAddress || current.to,
      subject: thread.subject.startsWith("Re:") ? thread.subject : `Re: ${thread.subject}`,
    }));
  }

  return (
    <div className="email-sender-layout">
      <article className="workflow-panel">
        <span className="toc-card-kicker">Gmail outreach</span>
        <h2>Send email</h2>
        <p className="muted" style={{ marginBottom: "1rem" }}>
          Compose recruiter follow-ups from CareerOS. Uses Gmail SMTP configured on the Python backend.
        </p>

        {gmailReady === null ? (
          <p className="muted">Checking Gmail connection…</p>
        ) : gmailReady ? (
          <p className="email-sender-status email-sender-status--ok">
            Connected as <strong>{gmailUser}</strong>
          </p>
        ) : (
          <div className="email-sender-setup">
            <p className="email-sender-status email-sender-status--warn">
              Gmail is not configured on the API yet.
            </p>
            <p className="muted">
              Add <code>GMAIL_USER</code> and <code>GMAIL_APP_PASSWORD</code> to{" "}
              <code>apps/api/.env</code>, then restart the API. See <code>docs/email.md</code> for App Password
              setup.
            </p>
            <button type="button" className="btn btn-sm" onClick={() => void checkGmail()}>
              Retry connection
            </button>
          </div>
        )}

        <form className="referral-form email-sender-form" onSubmit={handleSend}>
          <div className="referral-form-grid">
            <label>
              To *
              <input
                type="email"
                value={form.to}
                onChange={(e) => setForm({ ...form, to: e.target.value })}
                placeholder="recruiter@company.com"
                required
                disabled={!gmailReady || sending}
              />
            </label>
            <label className="email-sender-subject">
              Subject *
              <input
                value={form.subject}
                onChange={(e) => setForm({ ...form, subject: e.target.value })}
                placeholder="Following up on Staff Engineer role"
                required
                disabled={!gmailReady || sending}
              />
            </label>
          </div>
          <label>
            Message *
            <textarea
              rows={6}
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
              placeholder="Hi — I wanted to follow up on my application…"
              required
              disabled={!gmailReady || sending}
            />
          </label>
          <div className="email-sender-actions">
            <button type="submit" className="btn btn-primary" disabled={!gmailReady || sending}>
              {sending ? "Sending…" : "Send email"}
            </button>
          </div>
        </form>

        {status ? <p className="email-sender-status email-sender-status--ok">{status}</p> : null}
        {error ? <p className="email-sender-status email-sender-status--warn">{error}</p> : null}
      </article>

      <article className="workflow-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Inbox</span>
            <h2>Recruiter threads</h2>
          </div>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void loadThreads()}
            disabled={!gmailReady || loadingThreads}
          >
            {loadingThreads ? "Loading…" : "Refresh"}
          </button>
        </div>
        <p className="muted" style={{ marginBottom: "1rem" }}>
          Recent Gmail messages matching recruiter, hiring, interview, or application subjects.
        </p>
        {threads.length ? (
          <div className="dashboard-list">
            {threads.map((thread) => (
              <div className="profile-answer-row email-thread-row" key={thread.uid}>
                <div>
                  <h3>{thread.subject}</h3>
                  <span>
                    {[thread.fromName || thread.fromAddress, new Date(thread.date).toLocaleString()]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => applyThreadReply(thread)}
                  disabled={!gmailReady}
                >
                  Reply
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted dashboard-empty">
            {loadingThreads ? "Loading threads…" : "Click Refresh to load recruiter-related email threads."}
          </p>
        )}
      </article>
    </div>
  );
}
