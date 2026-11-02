import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';

export interface FieldMapping {
  id: string;
  applicationId: string;
  sessionId: string;
  rawLabel: string;
  normalizedLabel: string;
  fieldType: string;
  canonicalKey?: string;
  proposedValue?: string;
  finalValue?: string;
  confidence: number; // score: 0 to 1
  source: "profile" | "learned_answer" | "manual" | "template" | "skipped";
  wasEdited: boolean;
  createdAt: string;
  /** ATS host where this mapping was learned (e.g. boards.greenhouse.io). */
  domain?: string;
}

let memoryCache: FieldMapping[] = [];

export async function getFieldMappings(): Promise<FieldMapping[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<FieldMapping[]>('fieldMappings', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function saveFieldMappings(mappings: Omit<FieldMapping, 'id' | 'createdAt'>[]): Promise<FieldMapping[]> {
  const list = await getFieldMappings();
  const now = getCurrentDateTimeISO();
  const saved: FieldMapping[] = [];

  for (const m of mappings) {
    const item: FieldMapping = {
      ...m,
      id: generateId(),
      createdAt: now
    };
    list.push(item);
    saved.push(item);

    if (typeof indexedDB !== 'undefined') {
      try {
        await runInStore<void>('fieldMappings', 'readwrite', (store) => store.put(item));
      } catch {
        // Fallback
      }
    }
  }

  if (typeof indexedDB === 'undefined') {
    memoryCache = list;
  }
  return saved;
}

export async function saveFieldMapping(mapping: FieldMapping): Promise<FieldMapping> {
  if (typeof indexedDB === 'undefined') {
    const list = memoryCache.filter(m => m.id !== mapping.id);
    list.push(mapping);
    memoryCache = list;
  } else {
    try {
      await runInStore<void>('fieldMappings', 'readwrite', (store) => store.put(mapping));
    } catch {
      // fallback
    }
  }
  return mapping;
}
