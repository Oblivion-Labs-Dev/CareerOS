import { Suspense } from "react";
import { WorkflowPage } from "@/components/scaffold-page";
import { JobDiscoverDashboard } from "@/components/jobs/job-discover-dashboard";

export default function JobDiscoverPage() {
  return (
    <WorkflowPage
      title="Browse Jobs"
      eyebrow="Job Ingestion & Discovery"
      subtitle="Search and browse 250,000+ jobs across authoritative ATS platforms, Big Tech, curated remote APIs, and startup feeds with multi-source deduplication, profile relevancy, and 1-click AI prep."
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
