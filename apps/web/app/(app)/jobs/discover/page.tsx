import { Suspense } from "react";
import { WorkflowPage } from "@/components/scaffold-page";
import { JobDiscoverDashboard } from "@/components/jobs/job-discover-dashboard";

export default function JobDiscoverPage() {
  return (
    <WorkflowPage
      title="Job Scraper"
      eyebrow="Intelligence Layer"
      subtitle="Scrape 600+ companies across ATS boards, Big Tech, and Apify — score roles against your profile, save to tracker, and outreach."
      primaryAction={{ href: "/profile", label: "Update profile" }}
      secondaryAction={{ href: "/dashboard", label: "Back to dashboard" }}
      outcomes={[
        "Pull fresh roles from major ATS career pages in one run.",
        "See relevancy scores based on your title, skills, and location.",
        "Filter by role family, freshness, and company before applying.",
      ]}
      focusAreas={[
        {
          title: "Multi-ATS scraping",
          description: "Greenhouse, Lever, Ashby, SmartRecruiters, Workday, and Workable boards.",
        },
        {
          title: "Profile-aware scoring",
          description: "Rescore after updating skills or target title on your profile.",
        },
        {
          title: "Dashboard pipeline",
          description: "Saved roles flow into your dashboard application tracker.",
        },
      ]}
    >
      <Suspense fallback={<p className="muted">Loading job scraper…</p>}>
        <JobDiscoverDashboard />
      </Suspense>
    </WorkflowPage>
  );
}
