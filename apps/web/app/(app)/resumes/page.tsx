import { WorkflowPage } from "@/components/scaffold-page";

export default function ResumesPage() {
  return (
    <WorkflowPage
      title="Documents"
      eyebrow="Foundation"
      subtitle="Manage resumes and cover letters together so every application has the right supporting material."
      primaryAction={{ href: "/profile", label: "Review profile" }}
      secondaryAction={{ href: "/applications", label: "Open tracker" }}
      outcomes={[
        "Store a default resume plus targeted variants for different role families.",
        "Keep generated cover letters connected to the jobs and applications they support.",
        "Use parsed resume data to keep your profile and work history aligned.",
      ]}
      focusAreas={[
        {
          title: "Resume library",
          description: "Default resume, role-specific variants, parsed data, and attachment readiness.",
        },
        {
          title: "Cover letters",
          description: "Drafts generated from job context and your profile, saved with the relevant opportunity.",
        },
        {
          title: "Fit check",
          description: "Compare the selected documents against the job context before submitting.",
        },
      ]}
    />
  );
}
