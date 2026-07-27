import { generateId } from './id';

export interface ApplyQueueItem {
  id: string;
  url: string;
  company: string;
  role: string;
  location?: string;
  platform?: string;
  addedAt: string;
  status: 'queued' | 'in_progress' | 'done' | 'skipped';
}

const STORAGE_KEY = 'applyPilotQueue';

export async function getApplyQueue(): Promise<ApplyQueueItem[]> {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  const list = stored[STORAGE_KEY];
  return Array.isArray(list) ? (list as ApplyQueueItem[]) : [];
}

export async function saveApplyQueue(items: ApplyQueueItem[]): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEY]: items });
}

export async function addToApplyQueue(item: Omit<ApplyQueueItem, 'id' | 'addedAt' | 'status'>): Promise<ApplyQueueItem> {
  const queue = await getApplyQueue();
  const normalized = item.url.split('?')[0];
  const existing = queue.find((q) => q.url.split('?')[0] === normalized);
  if (existing) return existing;

  const entry: ApplyQueueItem = {
    id: generateId(),
    ...item,
    addedAt: new Date().toISOString(),
    status: 'queued'
  };
  queue.push(entry);
  await saveApplyQueue(queue);
  return entry;
}

export async function removeFromApplyQueue(id: string): Promise<void> {
  const queue = await getApplyQueue();
  await saveApplyQueue(queue.filter((item) => item.id !== id));
}

export async function markQueueItem(id: string, status: ApplyQueueItem['status']): Promise<void> {
  const queue = await getApplyQueue();
  const next = queue.map((item) => (item.id === id ? { ...item, status } : item));
  await saveApplyQueue(next);
}

export async function getNextQueuedJob(): Promise<ApplyQueueItem | null> {
  const queue = await getApplyQueue();
  return queue.find((item) => item.status === 'queued') || null;
}

export async function clearCompletedQueue(): Promise<void> {
  const queue = await getApplyQueue();
  await saveApplyQueue(queue.filter((item) => item.status === 'queued' || item.status === 'in_progress'));
}
