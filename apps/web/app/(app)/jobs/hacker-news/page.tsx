import { Suspense } from "react";
import { JobDiscoverDashboard } from "@/components/jobs/job-discover-dashboard";
import { WorkspaceLoading } from "@/components/ui/workspace-loading";

export default function HackerNewsHiringPage() {
  return (
    <Suspense fallback={<WorkspaceLoading label="Loading HN Hiring…" shape="grid" rows={6} />}>
      <JobDiscoverDashboard
        sourceFilter="hackernews"
        pagePath="/jobs/hacker-news"
        pageTitle="HN Hiring"
      />
    </Suspense>
  );
}
