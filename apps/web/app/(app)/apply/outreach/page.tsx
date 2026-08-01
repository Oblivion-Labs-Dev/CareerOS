import nextDynamic from "next/dynamic";
import Link from "next/link";
import { PageTitleWithStatus } from "@/components/page-title-with-status";

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
      <section className="apply-dashboard-hero apply-dashboard-hero--single">
        <div>
          <span className="toc-eyebrow">Apply · Outreach</span>
          <PageTitleWithStatus>Recruiter email campaigns</PageTitleWithStatus>
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
