"use client";

import { useCallback, useEffect, useState } from "react";

const REPAIR_BASE = process.env.NEXT_PUBLIC_REPAIR_ORCHESTRATOR_URL || "http://127.0.0.1:8090";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

type Incident = {
  fingerprint: string;
  title: string;
  severity: string;
  component: string;
  occurrenceCount: number;
  firstSeen: string;
  lastSeen: string;
  status: string;
};

type RepairTask = {
  taskId: string;
  incidentFingerprint: string;
  title: string;
  status: string;
  severity: string;
  component: string;
  occurrenceCount: number;
  agentBranch?: string;
  validation?: { passed?: boolean };
  review?: { decision?: string; riskLevel?: string; summary?: string };
  prTitle?: string;
  prBody?: string;
};

async function repairFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${REPAIR_BASE}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Repair API failed: ${path}`);
  }
  return res.json();
}

export default function RepairDashboardPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [tasks, setTasks] = useState<RepairTask[]>([]);
  const [message, setMessage] = useState<string>("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [incidentData, taskData] = await Promise.all([
        repairFetch<{ incidents: Incident[] }>("/incidents"),
        repairFetch<{ tasks: RepairTask[] }>("/tasks"),
      ]);
      setIncidents(incidentData.incidents);
      setTasks(taskData.tasks);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Failed to load repair dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function triggerDemoIncident() {
    setMessage("Triggering demo scraper error...");
    const res = await fetch(`${API_BASE}/dev/demo/unhandled-scraper-error`, { cache: "no-store" });
    const body = await res.json().catch(() => ({}));
    setMessage(`Demo triggered (${res.status}): ${JSON.stringify(body.detail ?? body)}`);
    await refresh();
  }

  async function runTaskAction(taskId: string, action: string) {
    setMessage(`Running ${action} for ${taskId}...`);
    await repairFetch(`/tasks/${taskId}/${action}`, { method: "POST" });
    await refresh();
    setMessage(`${action} completed for ${taskId}`);
  }

  async function createTask(fingerprint: string) {
    await repairFetch(`/incidents/${fingerprint}/tasks`, { method: "POST" });
    await refresh();
  }

  if (process.env.NODE_ENV === "production") {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <h1 className="text-2xl font-semibold">Not Found</h1>
        <p className="mt-2 text-muted-foreground">This page is unavailable outside local development.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl space-y-8 p-8">
      <header className="space-y-2">
        <p className="text-sm uppercase tracking-wide text-muted-foreground">Developer only</p>
        <h1 className="text-3xl font-semibold">Automated Repair Dashboard</h1>
        <p className="max-w-3xl text-muted-foreground">
          Local incident grouping, repair tasks, validation, and independent review. No automatic merge or deployment.
        </p>
        <div className="flex flex-wrap gap-3 pt-2">
          <button type="button" className="rounded-md bg-primary px-4 py-2 text-primary-foreground" onClick={() => void refresh()}>
            Refresh
          </button>
          <button type="button" className="rounded-md border px-4 py-2" onClick={() => void triggerDemoIncident()}>
            Trigger demo incident
          </button>
        </div>
        {message ? <p className="rounded-md border bg-muted/40 p-3 text-sm">{message}</p> : null}
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-medium">Open incidents</h2>
        {loading ? <p>Loading...</p> : null}
        <div className="overflow-x-auto rounded-lg border">
          <table className="min-w-full text-sm">
            <thead className="bg-muted/50 text-left">
              <tr>
                <th className="p-3">Severity</th>
                <th className="p-3">Component</th>
                <th className="p-3">Count</th>
                <th className="p-3">First / Last</th>
                <th className="p-3">Status</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((incident) => (
                <tr key={incident.fingerprint} className="border-t">
                  <td className="p-3">{incident.severity}</td>
                  <td className="p-3">{incident.component}</td>
                  <td className="p-3">{incident.occurrenceCount}</td>
                  <td className="p-3">
                    <div>{incident.firstSeen}</div>
                    <div className="text-muted-foreground">{incident.lastSeen}</div>
                  </td>
                  <td className="p-3">{incident.status}</td>
                  <td className="p-3">
                    <button type="button" className="rounded border px-2 py-1" onClick={() => void createTask(incident.fingerprint)}>
                      Create repair task
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-medium">Repair tasks</h2>
        <div className="space-y-4">
          {tasks.map((task) => (
            <article key={task.taskId} className="rounded-lg border p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-medium">{task.title}</h3>
                  <p className="text-sm text-muted-foreground">{task.taskId}</p>
                </div>
                <span className="rounded-full border px-3 py-1 text-sm">{task.status}</span>
              </div>
              <dl className="mt-3 grid gap-2 text-sm md:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">Component</dt>
                  <dd>{task.component}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Occurrences</dt>
                  <dd>{task.occurrenceCount}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Agent branch</dt>
                  <dd>{task.agentBranch || "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Validation</dt>
                  <dd>{task.validation?.passed === undefined ? "—" : task.validation.passed ? "passed" : "failed"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Review</dt>
                  <dd>{task.review?.decision || "—"} ({task.review?.riskLevel || "n/a"})</dd>
                </div>
              </dl>
              {task.review?.summary ? <p className="mt-2 text-sm">{task.review.summary}</p> : null}
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" className="rounded border px-2 py-1 text-sm" onClick={() => void runTaskAction(task.taskId, "approve-agent")}>
                  Approve agent execution
                </button>
                <button type="button" className="rounded border px-2 py-1 text-sm" onClick={() => void runTaskAction(task.taskId, "validate")}>
                  Retry validation
                </button>
                <button type="button" className="rounded border px-2 py-1 text-sm" onClick={() => void runTaskAction(task.taskId, "review")}>
                  Request independent review
                </button>
                <button type="button" className="rounded border px-2 py-1 text-sm" onClick={() => void runTaskAction(task.taskId, "close")}>
                  Close incident
                </button>
              </div>
              {task.prTitle ? (
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer">PR handoff draft</summary>
                  <pre className="mt-2 overflow-x-auto rounded bg-muted/40 p-3 whitespace-pre-wrap">{task.prTitle}{"\n\n"}{task.prBody}</pre>
                </details>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
