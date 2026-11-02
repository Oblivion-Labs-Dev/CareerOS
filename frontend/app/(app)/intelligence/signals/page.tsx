import { WorkflowPage } from "@/components/scaffold-page";
import { SignalsPanel } from "@/components/intelligence/signals-panel";

export default function SignalsPage() {
  return (
    <WorkflowPage
        title="Signals"
        eyebrow="Intelligence Layer"
        subtitle="Hiring intent from LinkedIn posts — find roles before they hit job boards."
        primaryAction={{ href: "/referrals", label: "Referrals" }}
        secondaryAction={{ href: "/recruiters", label: "Outreach" }}
        outcomes={["Classify hiring posts by intent score.", "Build a contact list from signals.", "Generate outreach from high-intent posts."]}
        focusAreas={[]}
      >
        <SignalsPanel />
      </WorkflowPage>
  );
}
