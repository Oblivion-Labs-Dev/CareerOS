import { WorkflowPage } from "@/components/scaffold-page";
import { IntelligenceTasksPanel } from "@/components/intelligence/tasks-panel";

export default function IntelligenceTasksPage() {
  return (
    <WorkflowPage
        title="Daily Tasks"
        eyebrow="Intelligence Layer"
        subtitle="CIOS daily and weekly rituals — outreach, memos, applications, and follow-ups that actually get interviews."
        primaryAction={{ href: "/jobs/discover", label: "Job Scraper" }}
        secondaryAction={{ href: "/dashboard#applications", label: "Applications" }}
        outcomes={["Track the five daily actions that compound.", "Weekly rituals for content and CIOS review.", "Tick items as you complete them — persisted locally."]}
        focusAreas={[]}
      >
        <IntelligenceTasksPanel />
      </WorkflowPage>
  );
}
