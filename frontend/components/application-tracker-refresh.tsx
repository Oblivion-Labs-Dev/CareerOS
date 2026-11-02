"use client";

import { useCallback, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

interface TrackerApplication {
  id?: string;
  roleTitle?: string;
  title?: string;
  companyName?: string;
  company?: string;
  status?: string;
  submittedAt?: string;
  updatedAt?: string;
  createdAt?: string;
}

interface TrackerSnapshot {
  applications?: TrackerApplication[];
}

function appCompany(app: TrackerApplication) {
  return app.companyName || app.company || "Unknown company";
}

function appRole(app: TrackerApplication) {
  return app.roleTitle || app.title || "Unknown role";
}

export function ApplicationTrackerRefresh() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<TrackerSnapshot | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${getClientApiBaseUrl()}/tracker/summary`, { cache: "no-store" });
      if (!res.ok) throw new Error("Could not reach the CareerOS API.");
      const data = (await res.json()) as TrackerSnapshot;
      setSnapshot(data);
      setCheckedAt(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Tracker refresh failed.");
    } finally {
      setLoading(false);
    }
  }, []);

  const applications = snapshot?.applications || [];
  const submitted = applications.filter((app) => app.status === "submitted");
  const autofilled = applications.filter((app) => app.status === "autofilled" || app.status === "ready_to_submit");

  return (
    <section className="dashboard-panel tracker-refresh-panel" aria-live="polite">
      <div className="dashboard-panel-header">
        <div>
          <span className="toc-card-kicker">Live sync</span>
          <h2>Tracker status</h2>
          <p className="muted dashboard-panel-copy">
            ApplyPilot saves to the Python API first. If a submit is missing here, click <strong>Submit</strong> on
            the floating widget after you submit on the employer site.
          </p>
        </div>
        <button type="button" className="btn-secondary dashboard-panel-action" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh tracker"}
        </button>
      </div>

      {error ? <p className="tracker-refresh-error">{error}</p> : null}

      {!error ? (
        <div className="tracker-refresh-stats">
          <div>
            <span>Submitted</span>
            <strong>{submitted.length}</strong>
          </div>
          <div>
            <span>Autofilled only</span>
            <strong>{autofilled.length}</strong>
          </div>
          <div>
            <span>Total records</span>
            <strong>{applications.length}</strong>
          </div>
          {checkedAt ? (
            <div>
              <span>Last checked</span>
              <strong>{checkedAt}</strong>
            </div>
          ) : null}
        </div>
      ) : null}

      {!error && autofilled.length ? (
        <div className="tracker-refresh-alert">
          <strong>{autofilled.length} application{autofilled.length === 1 ? "" : "s"} still marked autofilled.</strong>
          <p>
            {autofilled.map((app) => `${appCompany(app)} — ${appRole(app)}`).join(" · ")}. Open the job tab and click
            ApplyPilot <strong>Submit</strong> to move them into the submitted widgets.
          </p>
        </div>
      ) : null}
    </section>
  );
}
