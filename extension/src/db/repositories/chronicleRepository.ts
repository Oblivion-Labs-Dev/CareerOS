import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';

export interface Chronicle {
  id: string;
  applicationId?: string;
  jobId?: string;
  type:
    | "job_saved"
    | "page_parsed"
    | "field_answered"
    | "autofilled"
    | "status_changed"
    | "note_added"
    | "document_used"
    | "learned_answer_created"
    | "autofill_error"
    | "application_submitted";
  message: string;
  metadata?: object;
  createdAt: string;
}

let memoryCache: Chronicle[] = [];

export async function getChronicles(): Promise<Chronicle[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<Chronicle[]>('activityEvents', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function logChronicle(
  chronicleData: Omit<Chronicle, 'id' | 'createdAt'>
): Promise<Chronicle> {
  const list = await getChronicles();
  const now = getCurrentDateTimeISO();

  const newChronicle: Chronicle = {
    ...chronicleData,
    id: generateId(),
    createdAt: now
  };
  list.push(newChronicle);

  if (typeof indexedDB === 'undefined') {
    memoryCache = list;
  } else {
    try {
      const item = { ...newChronicle };
      await runInStore<void>('activityEvents', 'readwrite', (store) => store.put(item));
    } catch {
      memoryCache = list;
    }
  }
  return newChronicle;
}

export async function saveChronicle(chronicle: Chronicle): Promise<Chronicle> {
  if (typeof indexedDB === 'undefined') {
    const list = memoryCache.filter((e) => e.id !== chronicle.id);
    list.push(chronicle);
    memoryCache = list;
  } else {
    try {
      await runInStore<void>('activityEvents', 'readwrite', (store) => store.put(chronicle));
    } catch {
      // fallback
    }
  }
  return chronicle;
}
