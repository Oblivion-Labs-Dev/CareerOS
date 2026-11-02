"use client";

import nextDynamic from "next/dynamic";

const OutcomeRecorder = nextDynamic(
  () => import("@/components/applications/outcome-recorder").then((mod) => mod.OutcomeRecorder),
  { ssr: false },
);

export type ApplicationListItem = {
  id?: string;
  roleTitle?: string;
  title?: string;
  companyName?: string;
  company?: string;
  status?: string;
  platform?: string;
  submittedAt?: string;
  updatedAt?: string;
  createdAt?: string;
};

function appRole(app: ApplicationListItem) {
  return app.roleTitle || app.title || "Unknown role";
}

function appCompany(app: ApplicationListItem) {
  return app.companyName || app.company || "Unknown company";
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

export function ApplicationListWithOutcomes({ applications }: { applications: ApplicationListItem[] }) {
  if (!applications.length) {
    return <p className="muted">No applications yet. Save jobs from the extension or Job Scraper.</p>;
  }

  return (
    <div className="dashboard-list">
      {applications.map((app, index) => (
        <div className="dashboard-list-row" key={app.id || `${appCompany(app)}-${index}`}>
          <div>
            <h3>{appRole(app)}</h3>
            <span>{appCompany(app)}</span>
          </div>
          <div className="dashboard-row-meta">
            <span className="phase-pill">{app.status || "saved"}</span>
            <small>{formatDate(app.submittedAt || app.updatedAt || app.createdAt)}</small>
            {app.platform ? <small>{app.platform}</small> : null}
            {app.id ? <OutcomeRecorder applicationId={app.id} company={appCompany(app)} role={appRole(app)} /> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
