import { runInStore } from '../db';
import { generateId } from '../../shared/id';
import { getCurrentDateTimeISO } from '../../shared/dateUtils';

export interface Company {
  id: string;
  name: string;
  domain?: string;
  careersUrl?: string;
  createdAt: string;
  updatedAt: string;
}

let memoryCache: Company[] = [];

export async function getCompanies(): Promise<Company[]> {
  if (typeof indexedDB === 'undefined') return memoryCache;
  try {
    return await runInStore<Company[]>('companies', 'readonly', (store) => store.getAll());
  } catch {
    return memoryCache;
  }
}

export async function saveCompany(companyData: Omit<Company, 'id' | 'createdAt' | 'updatedAt'> & { id?: string }): Promise<Company> {
  const list = await getCompanies();
  const now = getCurrentDateTimeISO();

  let existing = companyData.id ? list.find(c => c.id === companyData.id) : list.find(c => c.name.toLowerCase() === companyData.name.toLowerCase());

  if (existing) {
    existing.domain = companyData.domain || existing.domain;
    existing.careersUrl = companyData.careersUrl || existing.careersUrl;
    existing.updatedAt = now;
  } else {
    existing = {
      id: companyData.id || generateId(),
      name: companyData.name,
      domain: companyData.domain,
      careersUrl: companyData.careersUrl,
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
      await runInStore<void>('companies', 'readwrite', (store) => store.put(item));
    } catch {
      memoryCache = list;
    }
  }
  return existing;
}
