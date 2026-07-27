import { WorkflowPage } from "@/components/scaffold-page";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { IntelligenceTasksPanel } from "@/components/intelligence/tasks-panel";

export default function IntelligenceTasksPage() {
  return (
    <>
      <div className="page-content"><BackendRequiredBanner /></div>
      <WorkflowPage
        title="Daily Tasks"
        eyebrow="Intelligence Layer"
        subtitle="CIOS daily and weekly rituals — outreach, memos, applications, and follow-ups that actually get interviews."
        primaryAction={{ href: "/jobs/discover", label: "Job Scraper" }}
        secondaryAction={{ href: "/applications", label: "Applications" }}
        outcomes={["Track the five daily actions that compound.", "Weekly rituals for content and CIOS review.", "Tick items as you complete them — persisted locally."]}
        focusAreas={[]}
      >
        <IntelligenceTasksPanel />
      </WorkflowPage>
    </>
  );
}
