import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';

export interface AutofillSession {
  id: string;
  applicationId: string;
  pageUrl: string;
  startedAt: string;
  completedAt?: string;
  fieldsDetected: number;
  fieldsFilled: number;
  fieldsSkipped: number;
  lowConfidenceCount: number;
  userApproved: boolean;
  finalAction: "reviewed" | "filled" | "cancelled";
}

let memoryCache: AutofillSession[] = [];

export async function getAutofillSessions(): Promise<AutofillSession[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<AutofillSession[]>('autofillSessions', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function saveAutofillSession(
  sessionData: Omit<AutofillSession, 'id' | 'startedAt'> & { id?: string; startedAt?: string }
): Promise<AutofillSession> {
  const list = await getAutofillSessions();
  const now = getCurrentDateTimeISO();

  let existing = sessionData.id ? list.find(s => s.id === sessionData.id) : null;

  if (existing) {
    existing.completedAt = sessionData.completedAt || now;
    existing.fieldsDetected = sessionData.fieldsDetected;
    existing.fieldsFilled = sessionData.fieldsFilled;
    existing.fieldsSkipped = sessionData.fieldsSkipped;
    existing.lowConfidenceCount = sessionData.lowConfidenceCount;
    existing.userApproved = sessionData.userApproved;
    existing.finalAction = sessionData.finalAction;
  } else {
    existing = {
      id: sessionData.id || generateId(),
      applicationId: sessionData.applicationId,
      pageUrl: sessionData.pageUrl,
      startedAt: sessionData.startedAt || now,
      completedAt: sessionData.completedAt,
      fieldsDetected: sessionData.fieldsDetected,
      fieldsFilled: sessionData.fieldsFilled,
      fieldsSkipped: sessionData.fieldsSkipped,
      lowConfidenceCount: sessionData.lowConfidenceCount,
      userApproved: sessionData.userApproved,
      finalAction: sessionData.finalAction
    };
    list.push(existing);
  }

  if (typeof indexedDB === 'undefined') {
    memoryCache = list;
  } else {
    try {
      const item = { ...existing };
      await runInStore<void>('autofillSessions', 'readwrite', (store) => store.put(item));
    } catch {
      memoryCache = list;
    }
  }
  return existing;
}
