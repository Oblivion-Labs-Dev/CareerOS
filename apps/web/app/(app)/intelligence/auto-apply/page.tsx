import { WorkflowPage } from "@/components/scaffold-page";
import { AutoApplyPanel } from "@/components/intelligence/auto-apply-panel";

export default function AutoApplyPage() {
  return (
    <WorkflowPage
        title="Auto Apply"
        eyebrow="Intelligence Layer"
        subtitle="Programmatic ATS submission for eligible roles — pairs with ApplyPilot for form fill."
        primaryAction={{ href: "/apply-pilot", label: "ApplyPilot" }}
        secondaryAction={{ href: "/intelligence/night-shift", label: "Night Shift" }}
        outcomes={["Configure role filters and run caps.", "Dry-run before live submission.", "Full log of every run."]}
        focusAreas={[]}
      >
        <AutoApplyPanel />
      </WorkflowPage>
  );
}
