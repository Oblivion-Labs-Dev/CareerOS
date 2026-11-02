"use client";

import { SidePanelPortal } from "@/components/side-panel-portal";

export type JobGapAnalysis = {
  overallScore: number;
  gapPercent: number;
  strongMatches: string[];
  missingQualifications: string[];
  potentialConcerns: string[];
  explanation: string;
  matchMethod?: string;
  matchSources?: Record<string, boolean>;
  jobRequirements: {
    required: string[];
    preferred: string[];
  };
  descriptionPreview?: string;
};

export type JobGapPanelJob = {
  id: string;
  title: string;
  companyName: string;
  location?: string;
  url?: string;
  relevancyScore?: number;
};

type Props = {
  open: boolean;
  loading: boolean;
  error: string;
  job: JobGapPanelJob | null;
  analysis: JobGapAnalysis | null;
  onClose: () => void;
};

function ListSection({
  title,
  items,
  empty,
  variant = "default",
}: {
  title: string;
  items: string[];
  empty: string;
  variant?: "default" | "ok" | "warn";
}) {
  return (
    <section className="job-gap-panel-section">
      <h3>{title}</h3>
      {items.length ? (
        <ul className={`job-gap-panel-list job-gap-panel-list--${variant}`}>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </section>
  );
}

export function JobMatchGapPanel({ open, loading, error, job, analysis, onClose }: Props) {
  if (!open) return null;

  const score = analysis?.overallScore ?? job?.relevancyScore ?? 0;
  const gap = analysis?.gapPercent ?? Math.max(0, 100 - score);

  return (
    <SidePanelPortal
      open={open}
      onClose={onClose}
      panelClassName="job-match-gap-panel"
      backdropAriaLabel="Close gap analysis"
      ariaLabelledBy="job-gap-panel-title"
    >
      <div className="aa-wizard-panel-inner">
          <header className="aa-wizard-header">
            <div>
              <p className="aa-wizard-eyebrow">Match gap analysis</p>
              <h2 id="job-gap-panel-title">{job?.title || "Role fit"}</h2>
              {job?.companyName ? <p className="muted">{job.companyName}{job.location ? ` · ${job.location}` : ""}</p> : null}
            </div>
            <button type="button" className="btn btn-sm btn-secondary" onClick={onClose}>
              Close
            </button>
          </header>

          <div className="aa-wizard-body">
            {loading ? (
              <div className="aa-wizard-body--loading">
                <span className="aa-wizard-loading-spinner" aria-hidden />
                <p><strong>Analyzing fit against your resume…</strong></p>
                <p className="muted">Comparing this job description to your profile and uploaded resume.</p>
              </div>
            ) : error ? (
              <p className="job-gap-panel-error" role="alert">{error}</p>
            ) : analysis ? (
              <>
                <div className="job-gap-panel-scores">
                  <div className="job-gap-panel-score job-gap-panel-score--match">
                    <span>Match</span>
                    <strong>{Math.round(score)}%</strong>
                  </div>
                  <div className="job-gap-panel-score job-gap-panel-score--gap">
                    <span>Gap</span>
                    <strong className="job-gap-panel-gap-value">{Math.round(gap)}%</strong>
                  </div>
                </div>

                {analysis.explanation ? (
                  <p className="job-gap-panel-summary">{analysis.explanation}</p>
                ) : null}

                <ListSection
                  title="What the job requires"
                  items={[
                    ...analysis.jobRequirements.required.slice(0, 12),
                    ...analysis.jobRequirements.preferred.slice(0, 6).map((item) => `${item} (preferred)`),
                  ]}
                  empty="No structured requirements found in the description."
                />

                <ListSection
                  title="Already in your resume / profile"
                  items={analysis.strongMatches}
                  empty="No strong overlaps detected yet — upload or sync your resume on Profile."
                  variant="ok"
                />

                <ListSection
                  title="Missing from your resume"
                  items={analysis.missingQualifications}
                  empty="No major gaps detected against parsed requirements."
                  variant="warn"
                />

                {analysis.potentialConcerns.length ? (
                  <ListSection
                    title="Potential concerns"
                    items={analysis.potentialConcerns}
                    empty=""
                    variant="warn"
                  />
                ) : null}

                {analysis.descriptionPreview &&
                !analysis.jobRequirements.required.length &&
                !analysis.jobRequirements.preferred.length ? (
                  <section className="job-gap-panel-section">
                    <h3>Job description excerpt</h3>
                    <p className="job-gap-panel-description">{analysis.descriptionPreview}</p>
                  </section>
                ) : null}

                <p className="muted text-sm job-gap-panel-meta">
                  Scored with {analysis.matchMethod === "qwen" ? "Qwen" : "heuristic matching"}
                  {analysis.matchSources?.resume ? " · includes uploaded resume" : " · profile only — upload resume for better analysis"}
                </p>

                {job?.url ? (
                  <a className="btn btn-sm btn-primary" href={job.url} target="_blank" rel="noreferrer">
                    Open job posting
                  </a>
                ) : null}
              </>
            ) : (
              <p className="muted">Could not load gap analysis. Try again or rescore jobs after uploading your resume.</p>
            )}
          </div>
      </div>
    </SidePanelPortal>
  );
}
