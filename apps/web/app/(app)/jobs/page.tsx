import { WorkflowPage } from "@/components/scaffold-page";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { fetchJson } from "@/lib/api";

export default async function JobsPage() {
  const data = await fetchJson<{ jobs: Array<{ title: string; companyName: string; url: string }> }>("/jobs").catch(
    () => ({ jobs: [] }),
  );

  return (
    <>
      <div className="page-content">
        <BackendRequiredBanner />
      </div>
      <WorkflowPage
      title="Jobs"
      eyebrow="Apply"
      subtitle="Collect roles worth considering, preserve the original context, and decide what deserves a real application."
      primaryAction={{ href: "/apply-pilot", label: "Open ApplyPilot" }}
      secondaryAction={{ href: "/apply/job-search-guide", label: "Job search guide" }}
      outcomes={[
        "Keep interesting roles out of browser-tab limbo.",
        "Compare opportunities before spending time on forms.",
        "Carry job context into resumes, cover letters, and applications.",
      ]}
      focusAreas={[
        {
          title: "Capture",
          description: "Save title, company, location, URL, and description from job pages.",
        },
        {
          title: "Evaluate",
          description: "Mark fit, priority, and whether the role is worth applying to.",
        },
        {
          title: "Move forward",
          description: "Send selected jobs into ApplyPilot, cover letters, and the pipeline.",
        },
      ]}
    >
      <section className="workflow-panel data-panel">
        <div className="data-panel-header">
          <div>
            <span className="toc-card-kicker">Saved roles</span>
            <h2>{data.jobs.length === 0 ? "No saved jobs yet" : `${data.jobs.length} saved jobs`}</h2>
          </div>
        </div>
        {data.jobs.length === 0 ? (
          <p className="muted">Use ApplyPilot on a job page to save the role before you start the application.</p>
        ) : (
          <div className="data-list">
            {data.jobs.map((job) => (
              <a className="data-row" href={job.url} key={job.url} target="_blank" rel="noreferrer">
                <div>
                  <h3>{job.title}</h3>
                  <span>{job.companyName}</span>
                </div>
                <span className="data-row-action">Open</span>
              </a>
            ))}
          </div>
        )}
      </section>
    </WorkflowPage>
    </>
  );
}
