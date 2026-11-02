import { getApiBase } from './apiConfig';

export interface CareerOsDiscoverJob {
  id: string;
  companyName: string;
  title: string;
  location?: string;
  url?: string;
  relevancyScore?: number;
  salaryRange?: string;
  employmentType?: string;
  h1bStatus?: string;
  h1bLabel?: string;
  keywordsMatched?: string[];
  color?: string;
}

export async function lookupDiscoverJobByUrl(pageUrl: string): Promise<CareerOsDiscoverJob | null> {
  try {
    const base = await getApiBase();
    const params = new URLSearchParams({ url: pageUrl });
    const res = await fetch(`${base}/jobs/discover/lookup?${params.toString()}`, {
      method: 'GET',
      headers: { Accept: 'application/json' }
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { success?: boolean; job?: CareerOsDiscoverJob };
    return data.success && data.job ? data.job : null;
  } catch {
    return null;
  }
}

export async function saveDiscoverJobToCareerOs(jobId: string): Promise<boolean> {
  try {
    const base = await getApiBase();
    const res = await fetch(`${base}/jobs/discover/${encodeURIComponent(jobId)}/save`, {
      method: 'POST',
      headers: { Accept: 'application/json' }
    });
    if (!res.ok) return false;
    const data = (await res.json()) as { success?: boolean };
    return Boolean(data.success);
  } catch {
    return false;
  }
}
