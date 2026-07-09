import { jobPostingKey } from './jobUrlMatching';

export interface PageSubmitRecord {
  url: string;
  company: string;
  role: string;
  submittedAt: string;
  platform?: string;
}

const STORAGE_KEY = 'applypilot-page-submits';

function pageKey(url: string): string {
  return jobPostingKey(url) || url.split('?')[0];
}

export async function getPageSubmitRecord(url: string): Promise<PageSubmitRecord | null> {
  const key = pageKey(url);
  const stored = await chrome.storage.session.get(STORAGE_KEY);
  const map = (stored[STORAGE_KEY] || {}) as Record<string, PageSubmitRecord>;
  return map[key] || null;
}

export async function markPageSubmitted(
  url: string,
  info: Omit<PageSubmitRecord, 'url'>
): Promise<void> {
  const key = pageKey(url);
  const stored = await chrome.storage.session.get(STORAGE_KEY);
  const map = (stored[STORAGE_KEY] || {}) as Record<string, PageSubmitRecord>;
  map[key] = { url, ...info };
  await chrome.storage.session.set({ [STORAGE_KEY]: map });
}
