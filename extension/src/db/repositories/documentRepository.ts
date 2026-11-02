import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';

export interface DocumentRecord {
  id: string;
  type: "resume" | "cover_letter";
  label: string;
  fileName?: string;
  roleTarget?: string;
  companyTarget?: string;
  version?: string;
  textSnapshot?: string;
  createdAt: string;
  updatedAt: string;
  active: boolean;
}

let memoryCache: DocumentRecord[] = [];

export async function getDocuments(): Promise<DocumentRecord[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<DocumentRecord[]>('documents', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function saveDocument(
  docData: Omit<DocumentRecord, 'id' | 'createdAt' | 'updatedAt'> & { id?: string }
): Promise<DocumentRecord> {
  const list = await getDocuments();
  const now = getCurrentDateTimeISO();

  let existing = docData.id ? list.find(d => d.id === docData.id) : null;

  if (existing) {
    existing.label = docData.label;
    existing.fileName = docData.fileName || existing.fileName;
    existing.roleTarget = docData.roleTarget || existing.roleTarget;
    existing.companyTarget = docData.companyTarget || existing.companyTarget;
    existing.version = docData.version || existing.version;
    existing.textSnapshot = docData.textSnapshot || existing.textSnapshot;
    existing.active = docData.active;
    existing.updatedAt = now;
  } else {
    existing = {
      id: docData.id || generateId(),
      type: docData.type,
      label: docData.label,
      fileName: docData.fileName,
      roleTarget: docData.roleTarget,
      companyTarget: docData.companyTarget,
      version: docData.version,
      textSnapshot: docData.textSnapshot,
      active: docData.active,
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
      await runInStore<void>('documents', 'readwrite', (store) => store.put(item));
    } catch {
      memoryCache = list;
    }
  }
  return existing;
}

export async function deleteDocument(id: string): Promise<void> {
  const list = await getDocuments();
  const filtered = list.filter(d => d.id !== id);
  memoryCache = filtered;

  if (typeof indexedDB !== 'undefined') {
    try {
      await runInStore<void>('documents', 'readwrite', (store) => store.delete(id));
    } catch {
      // Ignored
    }
  }
}
