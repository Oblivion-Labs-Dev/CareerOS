import dynamic from "next/dynamic";
import Link from "next/link";
import { PRODUCT_FEATURES } from "@career-os/core";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { getExtensionDistPath } from "@/lib/extension-dist-path";
const ApplyPilotInstaller = dynamic(
  () => import("@/components/apply-pilot-installer").then((mod) => mod.ApplyPilotInstaller),
  {
    loading: () => <p className="muted">Loading installer…</p>,
  },
);

const EmailSenderPanel = dynamic(
  () => import("@/components/email-sender-panel").then((mod) => mod.EmailSenderPanel),
  {
    loading: () => <p className="muted">Loading email sender…</p>,
  },
);

const CAPABILITIES = [
  {
    title: "Autofill",
    description: "Detect ATS fields, fill known profile values, and keep risky fields reviewable.",
  },
  {
    title: "Learning",
    description: "Remember unknown field mappings and recurring screening answers for future applications.",
  },
  {
    title: "Tracking",
    description: "Save jobs and applications into the CareerOS backend so the tracker stays current.",
  },
  {
    title: "Outreach",
    description: "Send recruiter follow-ups through Gmail and review recent hiring-related threads.",
  },
];

export default async function ApplyPilotPage() {
  const { distPath, distReady } = getExtensionDistPath();
  const applyPilot = PRODUCT_FEATURES.find((feature) => feature.id === "applypilot");

  return (
    <div className="page-content toc-page">
      <BackendRequiredBanner />

      <section className="toc-hero">        <span className="toc-eyebrow">ApplyPilot</span>
        <h1>The browser assistant for application forms.</h1>
        <p>
          Install ApplyPilot, connect it to the Python backend, and use it to fill applications while CareerOS
          keeps the tracker, learned answers, and job context organized.
        </p>
      </section>

      <section className="toc-grid" aria-label="ApplyPilot capabilities">
        {CAPABILITIES.map((capability) => (
          <article className="toc-card" key={capability.title}>
            <span className="toc-card-kicker">Capability</span>
            <h2>{capability.title}</h2>
            <p>{capability.description}</p>
          </article>
        ))}
      </section>

      {applyPilot && (
        <section className="focus-panel">
          <div className="focus-panel-copy">
            <span className="toc-eyebrow">Live now</span>
            <h2>{applyPilot.title}</h2>
            <p>{applyPilot.description}</p>
          </div>
          <div className="feature-installer-wrap">
            <h3>Install ApplyPilot</h3>
            <ApplyPilotInstaller initialDistPath={distPath} initialDistReady={distReady} />
          </div>
        </section>
      )}

      <section className="focus-panel email-sender-section" aria-label="Gmail outreach">
        <div className="focus-panel-copy">
          <span className="toc-eyebrow">Outreach</span>
          <h2>Gmail sender</h2>
          <p>
            Send application follow-ups and recruiter outreach from CareerOS. Connect Gmail on the API, compose
            here, and pull recent hiring threads when you need context. View batch send results on{" "}
            <Link href="/apply/outreach">Email Outreach</Link>.
          </p>
        </div>
        <EmailSenderPanel />
      </section>
    </div>
  );
}
