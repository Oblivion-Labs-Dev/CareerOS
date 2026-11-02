import { MinimalDashboard, type DiscoverJob, type DiscoverPayload } from "@/components/dashboard/minimal-dashboard";
import { defaultTopMatchesQuery } from "@/lib/career-workspace";
import { serverFetchJson } from "@/lib/server-api";

// Reads the session cookie (serverFetchJson), so this route can't be static.
export const dynamic = "force-dynamic";

async function loadInitialTopJobs(): Promise<DiscoverJob[]> {
  try {
    const payload = await serverFetchJson<DiscoverPayload>(
      `/jobs/discover?${defaultTopMatchesQuery().toString()}`,
      { revalidate: false },
    );
    return payload.jobs ?? [];
  } catch {
    // The client-side loadData effect in MinimalDashboard retries this same
    // request right after mount and surfaces its own error banner — no need
    // to duplicate that here. An empty first paint degrades to today's
    // behavior, not to a broken one.
    return [];
  }
}

export default async function DashboardPage() {
  const initialTopJobs = await loadInitialTopJobs();
  return <MinimalDashboard initialTopJobs={initialTopJobs} />;
}
