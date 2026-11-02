import { WorkflowPage } from "@/components/scaffold-page";
import { NetworkingWorkspace } from "@/components/networking/networking-workspace";

export default function NetworkingPage() {
  return (
    <WorkflowPage
      title="Contacts"
      eyebrow="Relationships"
      subtitle="A workspace per company — track who you know there, and draft a personalized first message grounded in your real background. No automated recruiter lookup (we don't have a people-search API wired up) — you add who you've found."
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
    >
      <NetworkingWorkspace />
    </WorkflowPage>
  );
}
