import { Suspense } from "react";
import { JobDiscoverDashboard } from "@/components/jobs/job-discover-dashboard";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";

export default function JobDiscoverPage() {
  return <Suspense fallback={<WorkspaceLoading label="Loading Browse Jobs…" />}><JobDiscoverDashboard/></Suspense>;
}
