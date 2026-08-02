import nextDynamic from "next/dynamic";
import { PageTitleWithStatus } from "@/components/page-title-with-status";
import { fetchHealth } from "@/lib/api";

export const dynamic = "force-dynamic";

const JobSearchAnalytics = nextDynamic(
  () => import("@/components/analytics/job-search-analytics").then((mod) => mod.JobSearchAnalytics),
  { loading: () => <p className="muted">Loading analytics…</p> },
);

export default async function AnalyticsPage() {
  let backendOnline = false;
  try {
    const health = await fetchHealth({ revalidate: 5 });
    backendOnline = health.status === "ok";
  } catch {
    backendOnline = false;
  }

  return (
    <div className="page-shell stack gap-lg">
      <header className="stack gap-xs">
        <p className="eyebrow">Grow</p>
        <PageTitleWithStatus>Progress &amp; Insights</PageTitleWithStatus>
        <p className="muted max-w-2xl">
          Pipeline conversion, market context, and outcome archives — one place to see what is working.
        </p>
      </header>

      {backendOnline ? (
        <JobSearchAnalytics />
      ) : (
        <p className="muted">Connect the backend to load analytics.</p>
      )}
    </div>
  );
}
