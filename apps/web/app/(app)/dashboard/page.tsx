import { MinimalDashboard } from "@/components/dashboard/minimal-dashboard";

export default function DashboardPage() {
  // The dashboard fetches its own jobs after paint and already shows a
  // skeleton while that runs. Waiting for the same request here held the
  // whole page, including the shell, until the API answered.
  return <MinimalDashboard initialTopJobs={[]} />;
}
