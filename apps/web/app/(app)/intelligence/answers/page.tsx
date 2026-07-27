import { WorkflowPage } from "@/components/scaffold-page";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { AnswerBankPanel } from "@/components/intelligence/answer-bank-panel";

export default function AnswerBankPage() {
  return (
    <>
      <div className="page-content"><BackendRequiredBanner /></div>
      <WorkflowPage
        title="Answer Bank"
        eyebrow="Intelligence Layer"
        subtitle="Smart screening-question answers — custom YAML overrides plus company-aware generated fallbacks."
        primaryAction={{ href: "/profile", label: "Profile" }}
        secondaryAction={{ href: "/apply-pilot", label: "ApplyPilot" }}
        outcomes={["Why company, about yourself, work auth, and more.", "Edit answers.yaml for full control.", "Used by ApplyPilot autofill and /questions/answer API."]}
        focusAreas={[]}
      >
        <AnswerBankPanel />
      </WorkflowPage>
    </>
  );
}
