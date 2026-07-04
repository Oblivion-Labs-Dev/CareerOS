import { WorkflowPage } from "@/components/scaffold-page";

export default function AnalyticsPage() {
  return (
    <WorkflowPage
      title="Analytics"
      eyebrow="Grow"
      subtitle="Turn search activity into a readable signal: what is moving, what is stuck, and where to adjust."
      primaryAction={{ href: "/applications", label: "Review pipeline" }}
      secondaryAction={{ href: "/roadmap", label: "See roadmap" }}
      outcomes={[
        "Understand conversion from saved jobs to submitted applications to responses.",
        "Spot stale applications, weak channels, and workload imbalance.",
        "Use outcomes to refine targeting instead of simply applying more.",
      ]}
      focusAreas={[
        {
          title: "Funnel",
          description: "Saved, applied, interviewing, offer, and closed stages.",
        },
        {
          title: "Activity",
          description: "Application pace, follow-ups, and interview prep over time.",
        },
        {
          title: "Learning",
          description: "Patterns by role type, company size, source, and resume variant.",
        },
      ]}
    />
  );
}
