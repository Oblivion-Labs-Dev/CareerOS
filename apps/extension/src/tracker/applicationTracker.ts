import { ApplicationRecord, ApplicationStatus } from '../shared/types';

function isChromeStorageAvailable(): boolean {
  return typeof chrome !== 'undefined' && chrome.storage !== undefined && chrome.storage.local !== undefined;
}

export async function getTrackerRecords(): Promise<ApplicationRecord[]> {
  if (!isChromeStorageAvailable()) {
    return [];
  }
  return new Promise((resolve) => {
    chrome.storage.local.get(['trackerRecords'], (res) => {
      resolve(res.trackerRecords || []);
    });
  });
}

export async function addTrackerRecord(
  recordData: Omit<ApplicationRecord, 'id' | 'date'>
): Promise<ApplicationRecord> {
  const records = await getTrackerRecords();
  const newRecord: ApplicationRecord = {
    ...recordData,
    id: Math.random().toString(36).substring(2, 9),
    date: new Date().toLocaleDateString()
  };
  records.push(newRecord);

  if (isChromeStorageAvailable()) {
    await new Promise<void>((resolve) => {
      chrome.storage.local.set({ trackerRecords: records }, () => resolve());
    });
  }
  return newRecord;
}

export async function updateTrackerStatus(id: string, status: ApplicationStatus): Promise<void> {
  const records = await getTrackerRecords();
  const record = records.find((r) => r.id === id);
  if (record) {
    record.status = status;
    if (isChromeStorageAvailable()) {
      await new Promise<void>((resolve) => {
        chrome.storage.local.set({ trackerRecords: records }, () => resolve());
      });
    }
  }
}

export async function deleteTrackerRecord(id: string): Promise<void> {
  const records = await getTrackerRecords();
  const filtered = records.filter((r) => r.id !== id);
  if (isChromeStorageAvailable()) {
    await new Promise<void>((resolve) => {
      chrome.storage.local.set({ trackerRecords: filtered }, () => resolve());
    });
  }
}
