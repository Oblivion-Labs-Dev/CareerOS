import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';

export interface Job {
  id: string;
  companyId: string;
  companyName: string;
  title: string;
  location?: string;
  jobUrl: string;
  sourcePlatform?: "greenhouse" | "lever" | "workday" | "ashby" | "linkedin" | "generic";
  jobDescriptionText?: string;
  jobDescriptionHash?: string;
  detectedSeniority?: string;
  detectedSkills?: string[];
  compensationText?: string;
  createdAt: string;
  updatedAt: string;
  lastSeenAt: string;
}

let memoryCache: Job[] = [];

export async function getJobs(): Promise<Job[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<Job[]>('jobs', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function saveJob(jobData: Omit<Job, 'id' | 'createdAt' | 'updatedAt' | 'lastSeenAt'> & { id?: string }): Promise<Job> {
  const list = await getJobs();
  const now = getCurrentDateTimeISO();

  let existing = jobData.id
    ? list.find(j => j.id === jobData.id)
    : list.find(j => j.jobUrl === jobData.jobUrl || (j.title === jobData.title && j.companyId === jobData.companyId));

  if (existing) {
    existing.location = jobData.location || existing.location;
    existing.sourcePlatform = jobData.sourcePlatform || existing.sourcePlatform;
    existing.jobDescriptionText = jobData.jobDescriptionText || existing.jobDescriptionText;
    existing.detectedSkills = jobData.detectedSkills || existing.detectedSkills;
    existing.compensationText = jobData.compensationText || existing.compensationText;
    existing.updatedAt = now;
    existing.lastSeenAt = now;
  } else {
    existing = {
      id: jobData.id || generateId(),
      companyId: jobData.companyId,
      companyName: jobData.companyName,
      title: jobData.title,
      location: jobData.location,
      jobUrl: jobData.jobUrl,
      sourcePlatform: jobData.sourcePlatform,
      jobDescriptionText: jobData.jobDescriptionText,
      jobDescriptionHash: jobData.jobDescriptionHash,
      detectedSeniority: jobData.detectedSeniority,
      detectedSkills: jobData.detectedSkills,
      compensationText: jobData.compensationText,
      createdAt: now,
      updatedAt: now,
      lastSeenAt: now
    };
    list.push(existing);
  }

  if (typeof indexedDB === 'undefined') {
    memoryCache = list;
  } else {
    try {
      const item = { ...existing };
      await runInStore<void>('jobs', 'readwrite', (store) => store.put(item));
    } catch {
      memoryCache = list;
    }
  }
  return existing;
}
