import { WorkflowPage } from "@/components/scaffold-page";

export default function SettingsPage() {
  return (
    <WorkflowPage
      title="Settings"
      eyebrow="Foundation"
      subtitle="Control how CareerOS stores data, syncs with the extension, and protects your job search workspace."
      primaryAction={{ href: "/profile", label: "Review profile" }}
      secondaryAction={{ href: "/roadmap", label: "View roadmap" }}
      outcomes={[
        "Keep API, extension, and local workspace settings understandable.",
        "Make privacy and data ownership controls visible before they are urgent.",
        "Separate product preferences from application content.",
      ]}
      focusAreas={[
        {
          title: "Sync",
          description: "Connection status between web, API, and ApplyPilot.",
        },
        {
          title: "Privacy",
          description: "Export, delete, retention, and local-first controls.",
        },
        {
          title: "Defaults",
          description: "Workspace preferences, application behavior, and notification rhythm.",
        },
      ]}
    />
  );
}
