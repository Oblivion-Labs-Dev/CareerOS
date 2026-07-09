import Link from "next/link";
import nextDynamic from "next/dynamic";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { fetchJson } from "@/lib/api";

const ApplicationTrackerRefresh = nextDynamic(
  () => import("@/components/application-tracker-refresh").then((mod) => mod.ApplicationTrackerRefresh),
  { loading: () => <p className="muted">Loading live tracker…</p> },
);

interface TrackerApplication {
  id?: string;
  roleTitle?: string;
  title?: string;
  companyName?: string;
  company?: string;
  status?: string;
  location?: string;
  platform?: string;
  source?: string;
  url?: string;
  notes?: string;
  createdAt?: string;
  updatedAt?: string;
  submittedAt?: string;
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
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function appSortDate(app: TrackerApplication) {
  return String(app.submittedAt || app.updatedAt || app.createdAt || "");
}

function appCompany(app: TrackerApplication) {
  return app.companyName || app.company || "Unknown company";
}

function appRole(app: TrackerApplication) {
  return app.roleTitle || app.title || "Unknown role";
}

function appUrl(app: TrackerApplication) {
  const url = app.url || app.notes;
  if (!url || !/^https?:\/\//i.test(url)) return undefined;
  return url;
}

export const dynamic = "force-dynamic";

export default async function ApplicationsPage() {
  const snapshot = await fetchJson<TrackerSnapshot>("/tracker/summary", { revalidate: false }).catch(
    (): TrackerSnapshot => ({}),
  );

  const applications = snapshot.applications || [];
  const jobsCount = snapshot.jobsCount ?? 0;
  const mappingsCount = snapshot.mappingsCount ?? 0;
  const learnedAnswersCount = snapshot.learnedAnswersCount ?? 0;
  const sessionsCount = snapshot.sessionsCount ?? 0;
  const counts = countStatus(applications);
  const submittedApplications = [...applications]
    .filter((app) => app.status === "submitted")
    .sort((a, b) => appSortDate(b).localeCompare(appSortDate(a)));
  const recentApplications = [...applications]
    .sort((a, b) => appSortDate(b).localeCompare(appSortDate(a)))
    .slice(0, 8);
  return (
    <div className="page-content apply-dashboard">
      <BackendRequiredBanner />

      <section className="apply-dashboard-hero apply-dashboard-hero--single">
        <div>
          <span className="toc-eyebrow">Application Tracker</span>
          <h1>One place for the application pipeline.</h1>
          <p>
            Track saved jobs, ApplyPilot submissions, autofill memory, follow-ups, and outcomes from the Python
            backend without splitting the same work across separate dashboard pages.
          </p>
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

      <ApplicationTrackerRefresh />

      {submittedApplications.length ? (
        <section className="dashboard-panel">
          <div className="dashboard-panel-header">
            <div>
              <span className="toc-card-kicker">Submitted</span>
              <h2>Application widgets</h2>
              <p className="muted dashboard-panel-copy">
                Each Submit click from ApplyPilot creates a separate card with company, role, platform, and date.
              </p>
            </div>
          </div>
          <div className="application-widget-grid">
            {submittedApplications.map((app, index) => {
              const href = appUrl(app);
              return (
                <article className="application-widget-card" key={app.id || `${appCompany(app)}-${index}`}>
                  <div className="application-widget-card-top">
                    {app.platform ? <span className="application-widget-platform">{app.platform}</span> : null}
                    <time dateTime={app.submittedAt || app.updatedAt}>{formatDate(app.submittedAt || app.updatedAt || app.createdAt)}</time>
                  </div>
                  <h3>{appCompany(app)}</h3>
                  <p className="application-widget-role">{appRole(app)}</p>
                  {app.location ? <p className="application-widget-location">{app.location}</p> : null}
                  <div className="application-widget-footer">
                    <span className="phase-pill">submitted</span>
                    {href ? (
                      <a href={href} target="_blank" rel="noreferrer" className="application-widget-link">
                        View posting
                      </a>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

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
              <div className="dashboard-list-row" key={app.id || `${appCompany(app)}-${index}`}>
                <div>
                  <h3>{appRole(app)}</h3>
                  <span>{appCompany(app)}</span>
                </div>
                <div className="dashboard-row-meta">
                  <span className="phase-pill">{app.status || "saved"}</span>
                  <small>{formatDate(app.submittedAt || app.updatedAt || app.createdAt)}</small>
                  {app.platform ? <small>{app.platform}</small> : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted dashboard-empty">
            Save or submit an application from ApplyPilot to start the tracker. After autofill, submit on the job site,
            then click <strong>Submit</strong> on the floating widget so company and date appear here.
          </p>
        )}
      </section>
    </div>
  );
}
