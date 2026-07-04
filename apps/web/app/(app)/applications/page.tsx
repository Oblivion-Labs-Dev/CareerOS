import Link from "next/link";
import { fetchHealth, fetchJson, getApiBaseUrl } from "@/lib/api";

interface TrackerApplication {
  id?: string;
  roleTitle?: string;
  title?: string;
  companyName?: string;
  company?: string;
  status?: string;
  createdAt?: string;
  updatedAt?: string;
  nextFollowUpAt?: string;
}

interface TrackerSnapshot {
  applications?: TrackerApplication[];
  jobsCount?: number;
  mappingsCount?: number;
  learnedAnswersCount?: number;
  sessionsCount?: number;
}

const FLOW = [
  { key: "saved", label: "Saved" },
  { key: "autofilled", label: "Autofilled" },
  { key: "submitted", label: "Submitted" },
  { key: "interviewing", label: "Interviewing" },
  { key: "offer", label: "Offer" },
];

function countStatus(applications: TrackerApplication[]) {
  return applications.reduce<Record<string, number>>((counts, app) => {
    const status = app.status || "saved";
    counts[status] = (counts[status] || 0) + 1;
    return counts;
  }, {});
}

function followUpsDue(applications: TrackerApplication[]) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return applications.filter((app) => {
    if (!app.nextFollowUpAt) return false;
    const next = new Date(app.nextFollowUpAt);
    next.setHours(0, 0, 0, 0);
    return next <= today && !["offer", "rejected", "withdrawn"].includes(String(app.status));
  }).length;
}

function responseRate(applications: TrackerApplication[]) {
  const submitted = applications.filter((app) => app.status === "submitted").length;
  const interviewing = applications.filter((app) => app.status === "interviewing").length;
  return submitted > 0 ? Math.round((interviewing / submitted) * 100) : 0;
}

function formatDate(value?: string) {
  if (!value) return "No date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No date";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
}

export default async function ApplicationsPage() {
  const [health, snapshot] = await Promise.all([
    fetchHealth().catch(() => ({ status: "offline" })),
    fetchJson<TrackerSnapshot>("/tracker/summary").catch((): TrackerSnapshot => ({})),
  ]);

  const applications = snapshot.applications || [];
  const jobsCount = snapshot.jobsCount ?? 0;
  const mappingsCount = snapshot.mappingsCount ?? 0;
  const learnedAnswersCount = snapshot.learnedAnswersCount ?? 0;
  const sessionsCount = snapshot.sessionsCount ?? 0;
  const counts = countStatus(applications);
  const recentApplications = [...applications]
    .sort((a, b) => String(b.updatedAt || b.createdAt || "").localeCompare(String(a.updatedAt || a.createdAt || "")))
    .slice(0, 8);
  const online = health.status === "ok";

  return (
    <div className="page-content apply-dashboard">
      <section className="apply-dashboard-hero">
        <div>
          <span className="toc-eyebrow">Application Tracker</span>
          <h1>One place for the application pipeline.</h1>
          <p>
            Track saved jobs, ApplyPilot submissions, autofill memory, follow-ups, and outcomes from the Python
            backend without splitting the same work across separate dashboard pages.
          </p>
        </div>
        <div className="api-status-card">
          <span className={`api-status-dot ${online ? "api-status-dot--online" : ""}`} />
          <div>
            <strong>{online ? "Backend online" : "Backend offline"}</strong>
            <span>{getApiBaseUrl()}</span>
          </div>
        </div>
      </section>

      <section className="dashboard-metric-grid" aria-label="Application tracker metrics">
        <div className="dashboard-metric-card">
          <span>Applications</span>
          <strong>{applications.length}</strong>
          <p>{followUpsDue(applications)} follow-ups due</p>
        </div>
        <div className="dashboard-metric-card">
          <span>Saved jobs</span>
          <strong>{jobsCount}</strong>
          <p>Ready to evaluate</p>
        </div>
        <div className="dashboard-metric-card">
          <span>Autofill memory</span>
          <strong>{mappingsCount}</strong>
          <p>{learnedAnswersCount} learned answers</p>
        </div>
        <div className="dashboard-metric-card">
          <span>Response rate</span>
          <strong>{responseRate(applications)}%</strong>
          <p>{sessionsCount} ApplyPilot sessions</p>
        </div>
      </section>

      <section className="dashboard-layout">
        <article className="dashboard-panel dashboard-panel--wide">
          <div className="dashboard-panel-header">
            <div>
              <span className="toc-card-kicker">Pipeline</span>
              <h2>Current flow</h2>
            </div>
            <Link href="/jobs" className="btn-secondary dashboard-panel-action">
              Review jobs
            </Link>
          </div>
          <div className="pipeline-bars">
            {FLOW.map((stage) => {
              const value =
                stage.key === "autofilled"
                  ? (counts.autofilled || 0) + (counts.parsed || 0) + (counts.ready_to_submit || 0)
                  : counts[stage.key] || 0;
              const width = applications.length ? Math.max(8, Math.round((value / applications.length) * 100)) : 8;
              return (
                <div className="pipeline-stage" key={stage.key}>
                  <div className="pipeline-stage-label">
                    <span>{stage.label}</span>
                    <strong>{value}</strong>
                  </div>
                  <div className="pipeline-track">
                    <span style={{ width: `${width}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </article>

        <article className="dashboard-panel">
          <span className="toc-card-kicker">Next actions</span>
          <h2>Keep momentum clear</h2>
          <div className="storage-list">
            <div>
              <span>Review saved jobs</span>
              <strong>{jobsCount}</strong>
            </div>
            <div>
              <span>Submit-ready</span>
              <strong>{counts.ready_to_submit || 0}</strong>
            </div>
            <div>
              <span>Follow-ups due</span>
              <strong>{followUpsDue(applications)}</strong>
            </div>
            <div>
              <span>Interviewing</span>
              <strong>{counts.interviewing || 0}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="dashboard-panel">
        <div className="dashboard-panel-header">
          <div>
            <span className="toc-card-kicker">Applications</span>
            <h2>{recentApplications.length ? "Latest records" : "No applications yet"}</h2>
          </div>
        </div>
        {recentApplications.length ? (
          <div className="dashboard-list">
            {recentApplications.map((app, index) => (
              <div className="dashboard-list-row" key={app.id || `${app.companyName}-${index}`}>
                <div>
                  <h3>{app.roleTitle || app.title || "Unknown role"}</h3>
                  <span>{app.companyName || app.company || "Unknown company"}</span>
                </div>
                <div className="dashboard-row-meta">
                  <span className="phase-pill">{app.status || "saved"}</span>
                  <small>{formatDate(app.updatedAt || app.createdAt)}</small>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted dashboard-empty">Save an application from ApplyPilot to start the tracker.</p>
        )}
      </section>
    </div>
  );
}
