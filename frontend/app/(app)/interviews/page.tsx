import { WorkflowPage } from "@/components/scaffold-page";

export default function InterviewsPage() {
  return (
    <WorkflowPage
      title="Interviews"
      eyebrow="Grow"
      subtitle="Prepare around the role, your proof points, and the actual stage you are entering next."
      primaryAction={{ href: "/dashboard#applications", label: "Choose opportunity" }}
      secondaryAction={{ href: "/analytics", label: "Review signals" }}
      outcomes={[
        "Keep behavioral stories, role notes, and prep tasks together.",
        "Move from generic practice to stage-specific preparation.",
        "Capture feedback after each round so the next one gets sharper.",
      ]}
      focusAreas={[
        {
          title: "Story bank",
          description: "Reusable examples for leadership, conflict, impact, and technical depth.",
        },
        {
          title: "Prep plan",
          description: "Company research, interviewer notes, and questions to ask.",
        },
        {
          title: "Debrief",
          description: "Post-interview notes, follow-up timing, and lessons learned.",
        },
      ]}
    />
  );
}
