import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ApplyPilot Privacy Policy — CareerOS",
  description: "Privacy policy for the CareerOS ApplyPilot browser extension.",
};

const SECTIONS = [
  {
    title: "Data we collect",
    body: `ApplyPilot stores the following locally in your browser and optionally syncs to your CareerOS API (which you control):

- Profile information you provide (name, email, phone, LinkedIn, work authorization, etc.)
- Resume and cover letter files you upload
- Job postings and application records you save
- Learned answers to custom application questions
- Field mapping preferences for ATS forms`,
  },
  {
    title: "Data we do not collect",
    body: `- ApplyPilot does not send data to Oblivion Labs or third-party analytics services by default
- No advertising trackers are included
- LLM features (when enabled) use your configured OpenRouter key on your backend`,
  },
  {
    title: "How data is used",
    body: "Data is used solely to autofill job applications, track your pipeline, and improve autofill accuracy through learned field mappings.",
  },
  {
    title: "Data storage",
    body: `- Browser: IndexedDB and extension storage
- Server: Your self-hosted or deployed CareerOS API (SQLite/PostgreSQL)

You choose the API URL. Default development URL is http://localhost:8000.`,
  },
  {
    title: "Permissions",
    body: `- storage — save profile and learned answers
- activeTab / scripting — scan and fill forms on pages you use
- host permissions — access job application pages and your CareerOS API`,
  },
  {
    title: "Contact",
    body: "For privacy questions, contact your CareerOS administrator or the support email listed on the Firefox Add-ons listing.",
  },
  {
    title: "Changes",
    body: "We may update this policy. Continued use after changes constitutes acceptance.",
  },
];

export default function ApplyPilotPrivacyPage() {
  return (
    <div className="landing" style={{ minHeight: "100vh" }}>
      <header className="landing-nav">
        <Link href="/" className="landing-nav-brand">
          <span className="brand-mark">OS</span>
          CareerOS
        </Link>
      </header>
      <article className="landing-section" style={{ maxWidth: 720, textAlign: "left" }}>
        <h1 className="landing-section-title" style={{ textAlign: "left" }}>
          ApplyPilot Privacy Policy
        </h1>
        <p className="muted" style={{ marginBottom: "2rem" }}>
          Last updated: July 2026
        </p>
        <p style={{ lineHeight: 1.7, marginBottom: "2rem" }}>
          CareerOS ApplyPilot (&quot;ApplyPilot&quot;) is a browser extension that helps you autofill job applications
          and sync data with your CareerOS account.
        </p>
        {SECTIONS.map((section) => (
          <section key={section.title} style={{ marginBottom: "1.75rem" }}>
            <h2 style={{ fontSize: "1.15rem", marginBottom: "0.5rem" }}>{section.title}</h2>
            <p className="muted" style={{ margin: 0, lineHeight: 1.65, whiteSpace: "pre-line" }}>
              {section.body}
            </p>
          </section>
        ))}
      </article>
    </div>
  );
}
