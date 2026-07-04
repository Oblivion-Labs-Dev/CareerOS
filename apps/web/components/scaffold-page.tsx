import Link from "next/link";

interface WorkflowPageProps {
  title: string;
  eyebrow: string;
  subtitle: string;
  primaryAction?: {
    href: string;
    label: string;
  };
  secondaryAction?: {
    href: string;
    label: string;
  };
  outcomes: string[];
  focusAreas: Array<{
    title: string;
    description: string;
  }>;
  children?: React.ReactNode;
}

export function WorkflowPage({
  title,
  eyebrow,
  subtitle,
  primaryAction,
  secondaryAction,
  outcomes,
  focusAreas,
  children,
}: WorkflowPageProps) {
  return (
    <div className="page-content workflow-page">
      <section className="workflow-hero">
        <div>
          <span className="toc-eyebrow">{eyebrow}</span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        {(primaryAction || secondaryAction) && (
          <div className="workflow-actions">
            {primaryAction && (
              <Link href={primaryAction.href} className="btn-primary">
                {primaryAction.label}
              </Link>
            )}
            {secondaryAction && (
              <Link href={secondaryAction.href} className="btn-secondary">
                {secondaryAction.label}
              </Link>
            )}
          </div>
        )}
      </section>

      <section className="workflow-grid" aria-label={`${title} overview`}>
        <article className="workflow-panel workflow-panel--main">
          <span className="toc-card-kicker">What this clarifies</span>
          <div className="workflow-checklist">
            {outcomes.map((outcome) => (
              <div className="workflow-check" key={outcome}>
                <span aria-hidden>✓</span>
                <p>{outcome}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="workflow-panel">
          <span className="toc-card-kicker">Coming into focus</span>
          <div className="workflow-focus-list">
            {focusAreas.map((area) => (
              <div className="workflow-focus" key={area.title}>
                <h2>{area.title}</h2>
                <p>{area.description}</p>
              </div>
            ))}
          </div>
        </article>
      </section>

      {children}
    </div>
  );
}

interface ScaffoldPageProps {
  title: string;
  subtitle: string;
  focus?: string;
}

export function ScaffoldPage({ title, subtitle, focus }: ScaffoldPageProps) {
  return (
    <WorkflowPage
      title={title}
      eyebrow="Workspace"
      subtitle={subtitle}
      primaryAction={{ href: "/roadmap", label: "View roadmap" }}
      outcomes={[focus ?? "This workspace is reserved for the next complete CareerOS workflow."]}
      focusAreas={[
        {
          title: "Next layer",
          description: "The page is ready for product-specific controls, saved data, and review states.",
        },
      ]}
    />
  );
}
