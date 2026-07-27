import { WorkflowPage } from "@/components/scaffold-page";
import { BackendRequiredBanner } from "@/components/backend-required-banner";
import { NightShiftPanel } from "@/components/intelligence/night-shift-panel";

export default function NightShiftPage() {
  return (
    <>
      <div className="page-content"><BackendRequiredBanner /></div>
      <WorkflowPage
        title="Night Shift"
        eyebrow="Intelligence Layer"
        subtitle="Queue Tier-2 roles for overnight form-fill. Tier-1 dream companies are never touched."
        primaryAction={{ href: "/jobs/discover", label: "Scrape jobs" }}
        secondaryAction={{ href: "/profile", label: "Profile" }}
        outcomes={["Hard block on Top-20 companies.", "One role per company per night.", "Morning review inbox before submit."]}
        focusAreas={[]}
      >
        <NightShiftPanel />
      </WorkflowPage>
    </>
  );
}
