import { H1bSponsorshipResult } from './h1bSponsorshipCheck';
import { UserProfile } from './types';

export interface H1bAwareWarning {
  level: 'warn' | 'info';
  title: string;
  message: string;
}

/** Warn visa seekers when job text suggests no sponsorship. */
export function getH1bAwareWarning(
  h1b: H1bSponsorshipResult,
  profile: Pick<UserProfile, 'sponsorship'>
): H1bAwareWarning | null {
  const needsSponsorship = profile.sponsorship?.trim().toLowerCase() === 'yes';
  if (!needsSponsorship) return null;

  if (h1b.status === 'unlikely') {
    return {
      level: 'warn',
      title: 'Sponsorship unlikely',
      message: `${h1b.reason}. You indicated you need visa sponsorship — consider skipping or confirming with the employer.`
    };
  }

  if (h1b.status === 'unknown') {
    return {
      level: 'info',
      title: 'Sponsorship unclear',
      message: 'No explicit sponsorship language found. Verify before investing time on this application.'
    };
  }

  return null;
}

export function shouldFilterH1bJob(
  h1bStatus: string | undefined,
  filter: 'all' | 'likely' | 'unlikely' | 'needs-friendly'
): boolean {
  if (filter === 'all') return true;
  if (filter === 'likely') return h1bStatus === 'likely';
  if (filter === 'unlikely') return h1bStatus === 'unlikely';
  if (filter === 'needs-friendly') return h1bStatus === 'likely' || h1bStatus === 'unknown';
  return true;
}
