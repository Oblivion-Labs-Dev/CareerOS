import { WorkflowPage } from "@/components/scaffold-page";

export default function NetworkingPage() {
  return (
    <WorkflowPage
      title="Contacts"
      eyebrow="Relationships"
      subtitle="Organize recruiters, warm paths, referrals, and lightweight outreach around the companies you actually care about."
      primaryAction={{ href: "/dashboard#applications", label: "Review pipeline" }}
      secondaryAction={{ href: "/jobs", label: "Match to jobs" }}
      outcomes={[
        "Track recruiters and relationship notes in the same place.",
        "See which companies already have a relationship path.",
        "Keep intro requests specific, timely, and tied to real roles.",
      ]}
      focusAreas={[
        {
          title: "Recruiting contacts",
          description: "Recruiter contacts, active conversations, ownership, and follow-up timing.",
        },
        {
          title: "Network",
          description: "Warm contacts, referrals, connection strength, and relationship context.",
        },
        {
          title: "Companies",
          description: "Target organizations grouped by priority, opportunity, and relationship coverage.",
        },
      ]}
    />
  );
}
