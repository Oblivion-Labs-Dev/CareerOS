"use client";

import { useState } from "react";
import { postJson } from "@/lib/api";

const OUTCOME_OPTIONS = [
  { value: "in_progress", label: "In progress" },
  { value: "interview_only", label: "Interview only" },
  { value: "hired", label: "Hired" },
  { value: "rejected", label: "Rejected" },
  { value: "no_response", label: "No response" },
  { value: "offer_declined", label: "Offer declined" },
];

type OutcomeRecorderProps = {
  applicationId: string;
  company: string;
  role: string;
};

export function OutcomeRecorder({ applicationId, company, role }: OutcomeRecorderProps) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState("rejected");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit() {
    setBusy(true);
    setMessage("");
    try {
      await postJson(`/applications/${applicationId}/outcome`, {
        status,
        notes,
        dateResolved: status === "in_progress" ? null : new Date().toISOString().slice(0, 10),
      });
      setMessage("Outcome archived.");
      setOpen(false);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to record outcome");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button type="button" className="btn btn-sm btn-secondary" onClick={() => setOpen(true)}>
        Record outcome
      </button>
    );
  }

  return (
    <div className="stack gap-sm" style={{ minWidth: 220 }}>
      <strong className="text-sm">
        {role} @ {company}
      </strong>
      <select className="input" value={status} onChange={(event) => setStatus(event.target.value)}>
        {OUTCOME_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <textarea
        className="input"
        rows={3}
        placeholder="What happened? What to do differently?"
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
      />
      <div className="flex gap-sm">
        <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => void submit()}>
          {busy ? "Saving…" : "Save archive"}
        </button>
        <button type="button" className="btn btn-sm btn-secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {message ? <p className="muted text-sm">{message}</p> : null}
    </div>
  );
}
