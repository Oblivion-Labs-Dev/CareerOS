import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';
import { isBetterCompanyName, isBetterRoleTitle, jobPostingKey, urlsReferToSameJob } from '../../shared/jobUrlMatching';

export interface Application {
  id: string;
  jobId: string;
  companyId: string;
  companyName: string; // denormalized for fast reads
  roleTitle: string; // denormalized for fast reads
  location?: string;
  platform?: string;
  source?: string;
  status: "saved" | "parsed" | "autofilled" | "ready_to_submit" | "submitted" | "interviewing" | "offer" | "rejected" | "withdrawn";
  priority: "low" | "medium" | "high";
  fitScore?: number;
  resumeUsedId?: string;
  coverLetterUsedId?: string;
  submittedAt?: string;
  nextFollowUpAt?: string;
  notes?: string;
  jobUrl?: string;
  createdAt: string;
  updatedAt: string;
}

let memoryCache: Application[] = [];

export async function getApplications(): Promise<Application[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<Application[]>('applications', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function countSubmittedApplications(): Promise<number> {
  const apps = await getApplications();
  return apps.filter((app) => app.status === 'submitted').length;
}

export async function findApplicationByUrl(url: string): Promise<Application | undefined> {
  const apps = await getApplications();
  return apps.find((app) => urlsReferToSameJob(app.notes || '', url));
}

export async function findApplicationForSubmit(options: {
  url: string;
  company?: string;
  role?: string;
}): Promise<Application | undefined> {
  const { url, company, role } = options;
  const apps = await getApplications();

  const byUrl = apps.find((app) => urlsReferToSameJob(app.notes || '', url));
  if (byUrl) return byUrl;

  const postingKey = jobPostingKey(url);
  if (postingKey) {
    const byPosting = apps.find((app) => jobPostingKey(app.notes || '') === postingKey);
    if (byPosting) return byPosting;
  }

  const openStatuses = new Set(['saved', 'parsed', 'autofilled', 'ready_to_submit']);
  if (company && role && company !== 'Unknown Company' && role !== 'Unknown Role') {
    const byCompanyRole = apps.find(
      (app) =>
        openStatuses.has(app.status) &&
        app.companyName.toLowerCase() === company.toLowerCase() &&
        app.roleTitle.toLowerCase() === role.toLowerCase()
    );
    if (byCompanyRole) return byCompanyRole;
  }

  if (role && role !== 'Unknown Role') {
    return apps.find((app) => openStatuses.has(app.status) && app.roleTitle.toLowerCase() === role.toLowerCase());
  }

  return undefined;
}

export async function saveApplication(
  appData: Omit<Application, 'id' | 'createdAt' | 'updatedAt'> & { id?: string }
): Promise<Application> {
  const list = await getApplications();
  const now = getCurrentDateTimeISO();

  let existing = appData.id
    ? list.find(a => a.id === appData.id)
    : list.find(a => a.jobId === appData.jobId);

  if (existing) {
    existing.companyName = isBetterCompanyName(appData.companyName, existing.companyName)
      ? appData.companyName
      : existing.companyName;
    existing.roleTitle = isBetterRoleTitle(appData.roleTitle, existing.roleTitle)
      ? appData.roleTitle
      : existing.roleTitle;
    existing.location = appData.location || existing.location;
    existing.platform = appData.platform || existing.platform;
    existing.source = appData.source || existing.source;
    existing.status = appData.status;
    existing.priority = appData.priority;
    existing.fitScore = appData.fitScore !== undefined ? appData.fitScore : existing.fitScore;
    existing.resumeUsedId = appData.resumeUsedId || existing.resumeUsedId;
    existing.coverLetterUsedId = appData.coverLetterUsedId || existing.coverLetterUsedId;
    existing.submittedAt = appData.submittedAt || existing.submittedAt;
    existing.nextFollowUpAt = appData.nextFollowUpAt || existing.nextFollowUpAt;
    existing.notes = appData.notes || existing.notes;
    existing.updatedAt = now;
  } else {
    existing = {
      id: appData.id || generateId(),
      jobId: appData.jobId,
      companyId: appData.companyId,
      companyName: appData.companyName,
      roleTitle: appData.roleTitle,
      location: appData.location,
      platform: appData.platform,
      source: appData.source,
      status: appData.status,
      priority: appData.priority,
      fitScore: appData.fitScore,
      resumeUsedId: appData.resumeUsedId,
      coverLetterUsedId: appData.coverLetterUsedId,
      submittedAt: appData.submittedAt,
      nextFollowUpAt: appData.nextFollowUpAt,
      notes: appData.notes,
      createdAt: now,
      updatedAt: now
    };
    list.push(existing);
  }

  if (typeof indexedDB === 'undefined') {
    memoryCache = list;
  } else {
    try {
      const item = { ...existing };
      await runInStore<void>('applications', 'readwrite', (store) => store.put(item));
    } catch {
      memoryCache = list;
    }
  }
  return existing;
}

export async function deleteApplication(id: string): Promise<void> {
  const list = await getApplications();
  const filtered = list.filter(a => a.id !== id);
  memoryCache = filtered;

  if (typeof indexedDB !== 'undefined') {
    try {
      await runInStore<void>('applications', 'readwrite', (store) => store.delete(id));
    } catch {
      // Ignored
    }
  }
}
