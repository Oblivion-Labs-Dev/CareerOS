import { WorkExperienceEntry, UserProfile } from './types';

/** Default work history — descriptions filled from resume on parse. */
export function resolveMostRecentEmployer(profile: UserProfile): string {
  const currentJob = profile.workExperience?.find((entry) => entry.currentlyEmployed);
  if (currentJob?.company?.trim()) return currentJob.company.trim();

  const latest = profile.workExperience?.[0]?.company;
  if (latest?.trim()) return latest.trim();

  if (profile.currentCompany?.trim()) return profile.currentCompany.trim();
  return '';
}

export const DEFAULT_WORK_EXPERIENCE: WorkExperienceEntry[] = [
  {
    jobTitle: 'Senior Software Engineer',
    company: 'Microsoft',
    location: 'Redmond WA',
    currentlyEmployed: true,
    startDate: '09/2025',
    endDate: '',
    description: ''
  },
  {
    jobTitle: 'Software Engineer',
    company: 'Amazon',
    location: 'Seattle WA',
    currentlyEmployed: false,
    startDate: '08/2019',
    endDate: '08/2025',
    description: ''
  },
  {
    jobTitle: 'Software Engineering Intern',
    company: 'Liquiron',
    location: 'San Jose CA',
    currentlyEmployed: false,
    startDate: '12/2018',
    endDate: '01/2019',
    description: ''
  },
  {
    jobTitle: 'Software Engineer',
    company: 'Persistent Systems',
    location: 'Pune India',
    currentlyEmployed: false,
    startDate: '09/2016',
    endDate: '07/2017',
    description: ''
  }
];

export function workExperienceKey(entry: WorkExperienceEntry): string {
  return `${entry.company?.trim().toLowerCase()}|${entry.jobTitle?.trim().toLowerCase()}`;
}

function companyKey(entry: WorkExperienceEntry): string {
  return entry.company?.trim().toLowerCase() || '';
}

export function mergeWorkExperienceLists(
  existing: WorkExperienceEntry[] | undefined,
  incoming: WorkExperienceEntry[],
  force = false
): WorkExperienceEntry[] {
  if (!incoming.length) return existing || [];
  if (!existing?.length || force) return incoming;

  const byKey = new Map(incoming.map((entry) => [workExperienceKey(entry), entry]));
  const byCompany = new Map<string, WorkExperienceEntry>();
  for (const entry of incoming) {
    const key = companyKey(entry);
    if (!key) continue;
    const current = byCompany.get(key);
    if (!current || (entry.description?.length || 0) > (current.description?.length || 0)) {
      byCompany.set(key, entry);
    }
  }

  const merged = existing.map((entry) => {
    const parsed =
      byKey.get(workExperienceKey(entry)) || byCompany.get(companyKey(entry));
    if (!parsed) return entry;
    return {
      ...entry,
      jobTitle: entry.jobTitle?.trim() || parsed.jobTitle,
      location: entry.location?.trim() || parsed.location,
      startDate: entry.startDate?.trim() || parsed.startDate,
      endDate: entry.endDate?.trim() || parsed.endDate || '',
      currentlyEmployed: entry.currentlyEmployed ?? parsed.currentlyEmployed,
      description: parsed.description?.trim() || entry.description || ''
    };
  });

  for (const entry of incoming) {
    const company = companyKey(entry);
    if (!company) continue;
    if (!merged.some((item) => companyKey(item) === company)) {
      merged.push(entry);
    }
  }

  const seenCompanies = new Set<string>();
  const deduped: WorkExperienceEntry[] = [];
  for (const entry of merged) {
    const company = companyKey(entry);
    if (company && seenCompanies.has(company)) continue;
    if (company) seenCompanies.add(company);
    deduped.push(entry);
  }

  return deduped;
}
