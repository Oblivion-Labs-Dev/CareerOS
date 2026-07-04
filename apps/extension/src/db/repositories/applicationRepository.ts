import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';

export interface Application {
  id: string;
  jobId: string;
  companyId: string;
  companyName: string; // denormalized for fast reads
  roleTitle: string; // denormalized for fast reads
  location?: string;
  status: "saved" | "parsed" | "autofilled" | "ready_to_submit" | "submitted" | "interviewing" | "offer" | "rejected" | "withdrawn";
  priority: "low" | "medium" | "high";
  fitScore?: number;
  resumeUsedId?: string;
  coverLetterUsedId?: string;
  submittedAt?: string;
  nextFollowUpAt?: string;
  notes?: string;
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
  const normalized = url.split('?')[0];
  const apps = await getApplications();
  return apps.find(
    (app) =>
      app.notes === url ||
      app.notes?.startsWith(normalized) ||
      (app.notes && url.startsWith(app.notes.split('?')[0]))
  );
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
