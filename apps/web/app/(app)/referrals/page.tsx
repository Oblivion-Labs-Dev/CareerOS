import { WorkflowPage } from "@/components/scaffold-page";
import { ReferralsManager } from "@/components/referrals-manager";

export default async function ReferralsPage() {
  return (
    <WorkflowPage
      title="Referrals"
      eyebrow="Relationships"
      subtitle="People who can refer you at target companies — track emails, LinkedIn, relationship context, and referral status."
      primaryAction={{ href: "/dashboard#applications", label: "Review pipeline" }}
      secondaryAction={{ href: "/networking", label: "All contacts" }}
      outcomes={[
        "Keep referral contacts separate from cold outreach lists.",
        "Know who can refer you at each company before you apply.",
        "Track whether you've asked, received a referral, or need follow-up.",
      ]}
      focusAreas={[
        {
          title: "Warm paths",
          description: "Former colleagues, alumni, managers, and recruiters with referral influence.",
        },
        {
          title: "Company mapping",
          description: "Tie each contact to a company and role so you know where they can help.",
        },
        {
          title: "Referral status",
          description: "Active, asked, referred, or inactive — so follow-ups stay clear.",
        },
      ]}
    >
      <ReferralsManager />
    </WorkflowPage>
  );
}
