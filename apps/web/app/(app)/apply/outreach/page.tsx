import nextDynamic from "next/dynamic";
import Link from "next/link";
import { BackendRequiredBanner } from "@/components/backend-required-banner";

const RecruiterOutreachDashboard = nextDynamic(
  () => import("@/components/recruiter-outreach-dashboard").then((mod) => mod.RecruiterOutreachDashboard),
  {
    loading: () => <p className="muted">Loading outreach dashboard…</p>,
  },
);

export const dynamic = "force-dynamic";

export default async function ApplyOutreachPage() {
  return (
    <div className="page-content apply-dashboard">
      <BackendRequiredBanner />

      <section className="apply-dashboard-hero apply-dashboard-hero--single">
        <div>
          <span className="toc-eyebrow">Apply · Outreach</span>
          <h1>Recruiter email campaigns</h1>
          <p>
            Review Gmail outreach batches, delivery status per recruiter, subjects sent, and campaign timing.
            Results are saved from the batch sender and synced through the CareerOS API.
          </p>
          <p className="muted" style={{ marginTop: "0.75rem" }}>
            Need to compose a one-off message? Use the{" "}
            <Link href="/apply-pilot">ApplyPilot Gmail sender</Link>.
          </p>
        </div>
      </section>

      <RecruiterOutreachDashboard />
    </div>
  );
}
