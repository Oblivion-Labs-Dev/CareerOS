import { ROADMAP_FEATURES, ROADMAP_PHASES, featuresByPhase } from "@career-os/core";
import { PriorityBadge, StatusBadge } from "@career-os/ui";

const PHASE_SUMMARIES: Record<number, string> = {
  1: "Get the source of truth and ApplyPilot workflow reliable.",
  2: "Turn applications into an intelligent pipeline with tailored material support.",
  3: "Bring recruiter follow-up and interview prep into the same operating rhythm.",
  4: "Use search data to guide decisions, coaching, skills, and compensation.",
  5: "Connect the broader ecosystem with automation, integrations, and ownership controls.",
};

function statusCounts(phase: number) {
  const features = featuresByPhase(phase);

  return {
    total: features.length,
    inProgress: features.filter((feature) => feature.status === "in-progress").length,
    planned: features.filter((feature) => feature.status === "planned").length,
    done: features.filter((feature) => feature.status === "done").length,
  };
}

export default function RoadmapPage() {
  const activeCount = ROADMAP_FEATURES.filter((feature) => feature.status === "in-progress").length;
  const plannedCount = ROADMAP_FEATURES.filter((feature) => feature.status === "planned").length;

  return (
    <div className="page-content toc-page">
      <section className="toc-hero">
        <span className="toc-eyebrow">Roadmap</span>
        <h1>A clearer path from MVP to full CareerOS.</h1>
        <p>
          The roadmap is grouped by product maturity, not internal module names, so the next layer of
          work is easy to understand at a glance.
        </p>
      </section>

      <section className="roadmap-summary" aria-label="Roadmap summary">
        <div>
          <span>Total tracked</span>
          <strong>{ROADMAP_FEATURES.length}</strong>
        </div>
        <div>
          <span>Active now</span>
          <strong>{activeCount}</strong>
        </div>
        <div>
          <span>Planned</span>
          <strong>{plannedCount}</strong>
        </div>
      </section>

      <section className="roadmap-timeline" aria-label="CareerOS roadmap phases">
        {ROADMAP_PHASES.map((phase) => {
          const features = featuresByPhase(phase.id);
          const counts = statusCounts(phase.id);

          return (
            <article className="roadmap-phase" key={phase.id}>
              <div className="roadmap-phase-main">
                <span className="toc-card-kicker">Phase {phase.id}</span>
                <h2>{phase.name}</h2>
                <p>{PHASE_SUMMARIES[phase.id]}</p>
                <div className="phase-metrics">
                  <span>{counts.total} items</span>
                  <span>{counts.inProgress} active</span>
                  <span>{counts.planned} planned</span>
                  {counts.done > 0 && <span>{counts.done} done</span>}
                </div>
              </div>
              <div className="roadmap-feature-stack">
                {features.slice(0, 4).map((feature) => (
                  <div className="roadmap-feature-row" key={feature.id}>
                    <div>
                      <h3>{feature.title}</h3>
                      <span>{feature.description}</span>
                    </div>
                    <div className="cos-badge-row">
                      <PriorityBadge priority={feature.priority} />
                      <StatusBadge status={feature.status} />
                    </div>
                  </div>
                ))}
                {features.length > 4 && (
                  <div className="roadmap-more">+ {features.length - 4} more supporting items</div>
                )}
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}
