import Link from "next/link";
import { GuideStep, InfoTooltip } from "@/components/job-search/guide-primitives";
import {
  AI_JOB_PORTALS,
  AI_MATCHING_PLATFORMS,
  BEYOND_PORTALS,
  BIG_TECH_AI_PLATFORMS,
  BIG_TECH_CAREER_PAGES,
  CAREER_AGENT_PLATFORMS,
  CAREEROS_AGENT_VISION,
  PRIMARY_JOB_PORTALS,
  RECOMMENDED_SENIOR_STACK,
  USE_SPARINGLY,
  qualityStars,
  worthUsingLabel,
} from "@/lib/job-search-portals";
import { GUIDE_TOOLTIPS, JOB_SEARCH_JOURNEY } from "@/lib/job-search-guide";
import {
  AI_REVIEWERS,
  ATS_SCORE_DISCLAIMER,
  RECRUITER_ACTUALLY_CARES,
  RESUME_CHECKER_TOOLS,
  SENIOR_RESUME_PRIORITIES,
  TOP_RESUME_TOOLS,
  freeTierLabel,
  ratingStars,
  worthItLabel,
} from "@/lib/resume-tools";

export function JobSearchGuide() {
  const journey = JOB_SEARCH_JOURNEY;

  return (
    <div className="page-content job-guide-page">
      <section className="job-guide-hero">
        <div>
          <span className="toc-eyebrow">Apply · Playbook</span>
          <h1>Job search guide</h1>
          <p>
            A step-by-step path for Senior, Staff, and Principal engineers — from resume prep through outreach,
            tracking, and landing interviews at top companies.
          </p>
        </div>
        <div className="job-portals-hero-actions">
          <Link href="/resumes" className="btn-secondary">
            Your resume
          </Link>
          <Link href="/applications" className="btn-secondary">
            Tracker
          </Link>
          <Link href="/apply/outreach" className="btn-primary">
            Outreach
          </Link>
        </div>
      </section>

      <nav className="job-guide-timeline" aria-label="Job search steps">
        {journey.map((item) => (
          <a key={item.id} href={`#${item.id}`} className="job-guide-timeline-step">
            <span className="job-guide-timeline-num">{item.step}</span>
            <span className="job-guide-timeline-label">{item.title}</span>
          </a>
        ))}
      </nav>

      <GuideStep
        id="prepare"
        step={1}
        title={journey[0].title}
        summary={journey[0].summary}
        tooltip={journey[0].tooltip}
      >
        <div className="job-guide-callout job-guide-callout--warn">
          <strong>ATS scores are often meaningless.</strong> {ATS_SCORE_DISCLAIMER}
          <InfoTooltip text={GUIDE_TOOLTIPS.atsScore} label="ATS scores" />
        </div>

        <div className="job-guide-subsection">
          <h3>
            Resume checkers ranked
            <InfoTooltip
              text="Compare tools by actionable feedback — not the headline score they show you."
              label="Resume checkers"
            />
          </h3>
          <div className="job-portals-table-wrap">
            <table className="job-portals-table">
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>ATS check</th>
                  <th>AI feedback</th>
                  <th>Free tier</th>
                  <th>Worth it?</th>
                </tr>
              </thead>
              <tbody>
                {RESUME_CHECKER_TOOLS.map((tool) => (
                  <tr key={tool.href}>
                    <td>
                      <a href={tool.href} target="_blank" rel="noreferrer" className="job-portals-link">
                        {tool.name}
                      </a>
                    </td>
                    <td>
                      <span className="job-portals-stars">{ratingStars(tool.atsCheck)}</span>
                    </td>
                    <td>
                      <span className="job-portals-stars">{ratingStars(tool.aiFeedback)}</span>
                    </td>
                    <td>{freeTierLabel(tool.freeTier)}</td>
                    <td>
                      <span className={`job-portals-worth job-portals-worth--${tool.worthIt === "yes" ? "yes" : "good"}`}>
                        {worthItLabel(tool.worthIt)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="job-guide-subsection">
          <h3>Top picks for experienced engineers</h3>
          <div className="job-portals-detail-grid">
            {TOP_RESUME_TOOLS.map((tool) => (
              <article className="job-portals-detail-card" key={tool.href}>
                <h4>
                  <a href={tool.href} target="_blank" rel="noreferrer">
                    {tool.name}
                  </a>
                </h4>
                <p>{tool.summary}</p>
                {tool.note ? <p className="job-portals-note-inline">{tool.note}</p> : null}
              </article>
            ))}
          </div>
        </div>

        <div className="job-guide-subsection">
          <h3>AI reviewers for deeper feedback</h3>
          <div className="job-portals-agent-grid">
            {AI_REVIEWERS.map((reviewer) => (
              <article className="job-portals-card" key={reviewer.href}>
                <h4>
                  <a href={reviewer.href} target="_blank" rel="noreferrer">
                    {reviewer.name}
                  </a>
                </h4>
                <p className="job-portals-great-for">
                  <strong>Strong at:</strong> {reviewer.strengths.join(", ")}
                </p>
                {reviewer.promptExample ? (
                  <blockquote className="resume-tools-prompt">{reviewer.promptExample}</blockquote>
                ) : null}
              </article>
            ))}
          </div>
        </div>

        <ul className="job-portals-checklist job-guide-checklist">
          {SENIOR_RESUME_PRIORITIES.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </GuideStep>

      <GuideStep
        id="discover"
        step={2}
        title={journey[1].title}
        summary={journey[1].summary}
        tooltip={journey[1].tooltip}
      >
        <div className="job-guide-callout">
          <strong>Priority order:</strong> LinkedIn Jobs → Levels.fyi → company career pages → Wellfound → Built In
          <InfoTooltip text={GUIDE_TOOLTIPS.linkedInFocus} label="Search priority" />
        </div>

        <div className="job-guide-subsection">
          <h3>
            AI job matching platforms
            <InfoTooltip text={GUIDE_TOOLTIPS.aiMatching} label="AI matching" />
          </h3>
          <div className="job-portals-table-wrap">
            <table className="job-portals-table">
              <thead>
                <tr>
                  <th>Platform</th>
                  <th>Best for</th>
                  <th>AI match</th>
                  <th>
                    Worth using
                    <InfoTooltip text={GUIDE_TOOLTIPS.worthUsing} label="Worth using" />
                  </th>
                </tr>
              </thead>
              <tbody>
                {AI_MATCHING_PLATFORMS.map((platform) => (
                  <tr key={platform.href}>
                    <td>
                      <a href={platform.href} target="_blank" rel="noreferrer" className="job-portals-link">
                        {platform.name}
                      </a>
                    </td>
                    <td>{platform.bestFor}</td>
                    <td>
                      <span className="job-portals-stars">{qualityStars(platform.aiMatching)}</span>
                    </td>
                    <td>
                      <span className={`job-portals-worth job-portals-worth--${platform.worthUsing}`}>
                        {worthUsingLabel(platform.worthUsing)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="job-guide-subsection">
          <h3>Traditional job boards</h3>
          <div className="job-portals-table-wrap">
            <table className="job-portals-table job-portals-table--compact">
              <thead>
                <tr>
                  <th>Portal</th>
                  <th>Best for</th>
                  <th>Quality</th>
                </tr>
              </thead>
              <tbody>
                {PRIMARY_JOB_PORTALS.map((portal) => (
                  <tr key={portal.href}>
                    <td>
                      <a href={portal.href} target="_blank" rel="noreferrer" className="job-portals-link">
                        {portal.name}
                      </a>
                      {portal.priority === "high" ? (
                        <span className="job-portals-badge job-portals-badge--high">Priority</span>
                      ) : null}
                    </td>
                    <td>{portal.bestFor}</td>
                    <td>
                      <span className="job-portals-stars">{qualityStars(portal.quality)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="job-guide-two-col">
          <div className="job-guide-subsection">
            <h3>Big Tech career pages</h3>
            <ul className="job-portals-company-grid">
              {BIG_TECH_CAREER_PAGES.map((company) => (
                <li key={company.href}>
                  <a href={company.href} target="_blank" rel="noreferrer">
                    {company.name}
                  </a>
                </li>
              ))}
            </ul>
          </div>
          <div className="job-guide-subsection">
            <h3>AI / LLM role boards</h3>
            <ul className="job-portals-link-list">
              {AI_JOB_PORTALS.map((portal) => (
                <li key={portal.href}>
                  <a href={portal.href} target="_blank" rel="noreferrer">
                    {portal.name}
                  </a>
                  <span className="job-portals-list-meta">{portal.bestFor}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </GuideStep>

      <GuideStep
        id="apply"
        step={3}
        title={journey[2].title}
        summary={journey[2].summary}
        tooltip={journey[2].tooltip}
      >
        <div className="job-guide-subsection">
          <h3>Recommended tool stack</h3>
          <ul className="job-portals-stack-list">
            {RECOMMENDED_SENIOR_STACK.map((item) => (
              <li key={item.tool}>
                {item.href ? (
                  <a href={item.href} target="_blank" rel="noreferrer" className="job-portals-link">
                    {item.tool}
                  </a>
                ) : (
                  <strong>{item.tool}</strong>
                )}
                <span>{item.role}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="job-guide-subsection">
          <h3>Best apply tools for Big Tech engineers</h3>
          <div className="job-portals-detail-grid">
            {BIG_TECH_AI_PLATFORMS.map((platform) => (
              <article className="job-portals-detail-card" key={platform.href}>
                <div className="job-portals-detail-header">
                  <h4>
                    <a href={platform.href} target="_blank" rel="noreferrer">
                      {platform.name}
                    </a>
                  </h4>
                  <span className="job-portals-stars">{qualityStars(platform.quality)}</span>
                </div>
                <p>{platform.summary}</p>
              </article>
            ))}
          </div>
        </div>

        <div className="job-guide-careeros-strip">
          <div>
            <strong>Apply with CareerOS</strong>
            <p>Use ApplyPilot to autofill forms and save jobs directly into your tracker.</p>
          </div>
          <Link href="/apply-pilot" className="btn btn-sm">
            Open ApplyPilot
          </Link>
        </div>

        <details className="job-guide-details">
          <summary>Lower-priority boards (use sparingly)</summary>
          <ul className="job-portals-link-list">
            {USE_SPARINGLY.map((portal) => (
              <li key={portal.href}>
                <a href={portal.href} target="_blank" rel="noreferrer">
                  {portal.name}
                </a>
                <span className="job-portals-list-meta">{portal.note || portal.bestFor}</span>
              </li>
            ))}
          </ul>
        </details>
      </GuideStep>

      <GuideStep
        id="outreach"
        step={4}
        title={journey[3].title}
        summary={journey[3].summary}
        tooltip={journey[3].tooltip}
      >
        <div className="job-guide-callout job-guide-callout--accent">
          <strong>Cold apply vs warm path</strong> — Senior interviews mostly come from referrals, recruiter replies,
          and direct outreach — not job board submissions alone.
          <InfoTooltip text={GUIDE_TOOLTIPS.coldVsWarm} label="Cold vs warm" />
        </div>

        <ul className="job-portals-checklist job-guide-checklist">
          {BEYOND_PORTALS.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>

        <div className="job-guide-careeros-links">
          <Link href="/referrals" className="job-portals-careeros-link">
            <strong>Referrals</strong>
            <span>Warm paths at target companies</span>
          </Link>
          <Link href="/apply/outreach" className="job-portals-careeros-link">
            <strong>Email Outreach</strong>
            <span>Recruiter campaigns with delivery tracking</span>
          </Link>
          <Link href="/networking" className="job-portals-careeros-link">
            <strong>Contacts</strong>
            <span>People to stay in touch with</span>
          </Link>
          <a
            href="https://www.zeekdata.com"
            target="_blank"
            rel="noreferrer"
            className="job-portals-careeros-link"
          >
            <strong>ZeekData</strong>
            <span>Recruiter emails and company intelligence</span>
          </a>
        </div>
      </GuideStep>

      <GuideStep
        id="track"
        step={5}
        title={journey[4].title}
        summary={journey[4].summary}
        tooltip={journey[4].tooltip}
      >
        <div className="job-guide-careeros-strip">
          <div>
            <strong>CareerOS Application Tracker</strong>
            <p>Log submissions, follow-ups, and outcomes from ApplyPilot and outreach in one place.</p>
          </div>
          <Link href="/applications" className="btn btn-sm">
            Open tracker
          </Link>
        </div>

        <p className="muted">
          External option:{" "}
          <a href="https://www.tealhq.com" target="_blank" rel="noreferrer" className="job-portals-link">
            Teal HQ
          </a>{" "}
          for resume versions, match scores, and pipeline tracking.
        </p>

        <details className="job-guide-details">
          <summary>Auto-apply career agents (use selectively)</summary>
          <p className="muted job-guide-footnote" style={{ marginTop: "0.65rem" }}>
            {GUIDE_TOOLTIPS.careerAgents}
          </p>
          <div className="job-portals-agent-grid">
            {CAREER_AGENT_PLATFORMS.map((agent) => (
              <article className="job-portals-card" key={agent.href}>
                <h4>
                  <a href={agent.href} target="_blank" rel="noreferrer">
                    {agent.name}
                  </a>
                </h4>
                <p>{agent.summary}</p>
                {agent.note ? <p className="job-portals-note-inline">{agent.note}</p> : null}
              </article>
            ))}
          </div>
        </details>
      </GuideStep>

      <GuideStep
        id="understand"
        step={6}
        title={journey[5].title}
        summary={journey[5].summary}
        tooltip={journey[5].tooltip}
      >
        <div className="job-guide-two-col">
          <article className="job-portals-card">
            <h3>What ATS systems filter on</h3>
            <ul className="job-portals-checklist">
              {RECRUITER_ACTUALLY_CARES.atsFilters.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
          <article className="job-portals-card">
            <h3>What humans evaluate after parsing</h3>
            <ul className="job-portals-checklist">
              {RECRUITER_ACTUALLY_CARES.humanReview.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </article>
        </div>

        <p className="muted job-guide-footnote">{RECRUITER_ACTUALLY_CARES.insight}</p>

        <div className="job-portals-vision-card">
          <span className="toc-card-kicker">CareerOS direction</span>
          <h3>{CAREEROS_AGENT_VISION.headline}</h3>
          <p>{CAREEROS_AGENT_VISION.intro}</p>
          <div className="job-portals-careeros-links">
            {CAREEROS_AGENT_VISION.careerOsToday.map((item) => (
              <Link key={item.href} href={item.href} className="job-portals-careeros-link">
                <strong>{item.label}</strong>
                <span>{item.description}</span>
              </Link>
            ))}
          </div>
        </div>
      </GuideStep>
    </div>
  );
}
