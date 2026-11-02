"use client";

import { useCallback, useEffect, useState } from "react";
import { getClientApiBaseUrl } from "@/lib/api";

type TaskItem = { key: string; label: string; done: boolean; notes?: string };

export function IntelligenceTasksPanel() {
  const [daily, setDaily] = useState<TaskItem[]>([]);
  const [weekly, setWeekly] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const base = getClientApiBaseUrl();
      const [todayRes, weekRes] = await Promise.all([
        fetch(`${base}/intelligence/tasks/today`, { cache: "no-store" }),
        fetch(`${base}/intelligence/tasks/week`, { cache: "no-store" }),
      ]);
      if (!todayRes.ok || !weekRes.ok) throw new Error("Failed to load tasks");
      const today = (await todayRes.json()) as { tasks: TaskItem[] };
      const week = (await weekRes.json()) as { tasks: TaskItem[] };
      setDaily(today.tasks || []);
      setWeekly(week.tasks || []);
    } catch {
      setError("Could not load daily tasks. Confirm the API is running.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggle(period: "daily" | "weekly", key: string, done: boolean) {
    try {
      await fetch(`${getClientApiBaseUrl()}/intelligence/tasks/tick`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ period, key, done: !done }),
      });
      void load();
    } catch {
      setError("Could not update task.");
    }
  }

  if (loading) return <p className="muted">Loading checklist…</p>;

  return (
    <div className="intelligence-panel">
      {error ? <p className="email-sender-status email-sender-status--warn">{error}</p> : null}
      <section className="workflow-panel">
        <span className="toc-card-kicker">Today</span>
        <h2>Daily CIOS checklist</h2>
        <ul className="intelligence-checklist">
          {daily.map((task) => (
            <li key={task.key}>
              <label>
                <input type="checkbox" checked={task.done} onChange={() => void toggle("daily", task.key, task.done)} />
                <span>{task.label}</span>
              </label>
            </li>
          ))}
        </ul>
      </section>
      <section className="workflow-panel">
        <span className="toc-card-kicker">This week</span>
        <h2>Weekly rituals</h2>
        <ul className="intelligence-checklist">
          {weekly.map((task) => (
            <li key={task.key}>
              <label>
                <input type="checkbox" checked={task.done} onChange={() => void toggle("weekly", task.key, task.done)} />
                <span>{task.label}</span>
              </label>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
