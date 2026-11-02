import { getApplications, Application } from '../repositories/applicationRepository';
import { getAutofillSessions } from '../repositories/autofillSessionRepository';

export interface DashboardMetrics {
  totalApplications: number;
  submittedCount: number;
  interviewCount: number;
  rejectedCount: number;
  responseRate: number; // percentage (0 to 100)
  weeklyAppliedCount: number;
  followUpsDue: number;
  statusCounts: Record<string, number>;
  topCompanies: { name: string; count: number }[];
}

export async function computeDashboardMetrics(): Promise<DashboardMetrics> {
  const applications = await getApplications();
  const sessions = await getAutofillSessions();

  const totalApplications = applications.length;

  let submittedCount = 0;
  let interviewCount = 0;
  let rejectedCount = 0;
  let followUpsDue = 0;
  let weeklyAppliedCount = 0;

  const statusCounts: Record<string, number> = {
    saved: 0,
    parsed: 0,
    autofilled: 0,
    ready_to_submit: 0,
    submitted: 0,
    interviewing: 0,
    offer: 0,
    rejected: 0,
    withdrawn: 0
  };

  const companyCounts: Record<string, number> = {};
  const oneWeekAgo = new Date();
  oneWeekAgo.setDate(oneWeekAgo.getDate() - 7);

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (const app of applications) {
    // Count status
    if (app.status in statusCounts) {
      statusCounts[app.status]++;
    }

    if (app.status === 'submitted') submittedCount++;
    if (app.status === 'interviewing') interviewCount++;
    if (app.status === 'rejected') rejectedCount++;

    // Weekly count (parse createdAt or submittedAt)
    const createdDate = new Date(app.createdAt);
    if (createdDate >= oneWeekAgo) {
      weeklyAppliedCount++;
    }

    // Follow-ups due
    if (app.nextFollowUpAt) {
      const followUpDate = new Date(app.nextFollowUpAt);
      followUpDate.setHours(0,0,0,0);
      if (followUpDate <= today && app.status !== 'rejected' && app.status !== 'offer' && app.status !== 'withdrawn') {
        followUpsDue++;
      }
    }

    // Top companies counts
    const compName = app.companyName || 'Unknown Company';
    companyCounts[compName] = (companyCounts[compName] || 0) + 1;
  }

  // Response Rate = interviewing / submitted (expressed as 0-100)
  const responseRate = submittedCount > 0 ? Math.round((interviewCount / submittedCount) * 100) : 0;

  // Format top companies
  const topCompanies = Object.entries(companyCounts)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);

  return {
    totalApplications,
    submittedCount,
    interviewCount,
    rejectedCount,
    responseRate,
    weeklyAppliedCount,
    followUpsDue,
    statusCounts,
    topCompanies
  };
}
