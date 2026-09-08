import { Suspense } from "react";
import { WorkflowPage } from "@/components/scaffold-page";
import { JobDiscoverDashboard } from "@/components/jobs/job-discover-dashboard";

export default function JobDiscoverPage() {
  return (
    <WorkflowPage
      title="Browse Jobs"
      eyebrow="A world of possibilities"
      subtitle="Find a role worth your next move. Explore fresh openings, compare your fit, and save the opportunities that feel right."
      primaryAction={{ href: "/profile", label: "Update profile" }}
      secondaryAction={{ href: "/dashboard", label: "Back to dashboard" }}
      outcomes={[
        "Browse deduplicated postings across Greenhouse, Lever, Ashby, Workday, Himalayas, WWR, and Big Tech.",
        "Sort by most recent posting dates or AI-scored profile relevancy.",
        "Filter by role, location, remote status, ATS platform, and sponsorship.",
      ]}
      focusAreas={[
        {
          title: "Multi-Source Ingestion",
          description: "Authoritative direct employer ATS APIs, Big Tech portals, and high-yield remote APIs.",
        },
        {
          title: "Profile-Aware Scoring",
          description: "Relevancy matches calculated from your target title, skills, and resume accomplishments.",
        },
        {
          title: "AI Prep & Autopilot",
          description: "One-click launch to AI Application Assistant for automated form prep and review.",
        },
      ]}
    >
      <Suspense fallback={<p className="muted">Loading Browse Jobs…</p>}>
        <JobDiscoverDashboard />
      </Suspense>
    </WorkflowPage>
  );
}
