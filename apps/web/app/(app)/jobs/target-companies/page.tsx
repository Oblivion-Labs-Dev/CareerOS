import { WorkflowPage } from "@/components/scaffold-page";
import { TargetCompanyJobsDashboard } from "@/components/jobs/target-company-jobs-dashboard";

export default function TargetCompanyJobsPage() {
  return (
    <WorkflowPage
      title="Target company jobs"
      eyebrow="Search & apply"
      subtitle="Weekly Oracle and DocuSign Senior Software Engineer pulls — filter by remote or Washington, refresh live, and copy a WhatsApp-ready list."
      primaryAction={{ href: "/dashboard#applications", label: "Open applications" }}
      secondaryAction={{ href: "/jobs", label: "Saved opportunities" }}
      outcomes={[
        "Keep Oracle and DocuSign senior SWE listings in one place.",
        "Filter quickly for remote or Washington-friendly roles.",
        "Refresh weekly and share links in WhatsApp format.",
      ]}
      focusAreas={[
        {
          title: "DocuSign live pull",
          description: "Fetched from careers.docusign.com API on each refresh.",
        },
        {
          title: "Oracle seed + verify",
          description: "Tracked from Oracle seed list with live link verification.",
        },
        {
          title: "Ask the agent weekly",
          description: 'Say “refresh target company jobs” to run the weekly skill.',
        },
      ]}
    >
      <TargetCompanyJobsDashboard />
    </WorkflowPage>
  );
}
