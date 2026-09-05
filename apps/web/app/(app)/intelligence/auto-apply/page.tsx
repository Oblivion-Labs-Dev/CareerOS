import { WorkflowPage } from "@/components/scaffold-page";
import { AutoApplyPanel } from "@/components/intelligence/auto-apply-panel";

export default function AutoApplyPage() {
  return (
    <WorkflowPage
        title="Auto Apply"
        eyebrow="Intelligence Layer"
        subtitle="Parallel saved-search lanes score and stage matches into Autopilot, all drawing from one shared daily cap."
        primaryAction={{ href: "/applications?tab=review", label: "Review Center" }}
        secondaryAction={{ href: "/intelligence/night-shift", label: "Night Shift" }}
        outcomes={["Up to 5 lanes, each with its own match bar and cap.", "Review-before-submit stays available per lane.", "Full log of every run."]}
        focusAreas={[]}
      >
        <AutoApplyPanel />
      </WorkflowPage>
  );
}
