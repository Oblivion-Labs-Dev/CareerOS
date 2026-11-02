export function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    // Check if running in a non-browser environment (like unit tests in Node.js)
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB is not available in this environment.'));
      return;
    }

    const request = indexedDB.open('arsenal_jobfill_db', 1);

    request.onupgradeneeded = () => {
      const db = request.result;

      if (!db.objectStoreNames.contains('companies')) {
        db.createObjectStore('companies', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('jobs')) {
        db.createObjectStore('jobs', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('applications')) {
        db.createObjectStore('applications', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('autofillSessions')) {
        db.createObjectStore('autofillSessions', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('fieldMappings')) {
        db.createObjectStore('fieldMappings', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('learnedAnswers')) {
        db.createObjectStore('learnedAnswers', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('documents')) {
        db.createObjectStore('documents', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('activityEvents')) {
        db.createObjectStore('activityEvents', { keyPath: 'id' });
      }
    };

    request.onsuccess = () => {
      resolve(request.result);
    };

    request.onerror = () => {
      reject(request.error);
    };
  });
}

/**
 * Standard helper to execute transaction actions in a promise-based wrapper
 */
export async function runInStore<T>(
  storeName: string,
  mode: IDBTransactionMode,
  callback: (store: IDBObjectStore) => IDBRequest | void
): Promise<T> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, mode);
    const store = transaction.objectStore(storeName);
    const req = callback(store);

    if (req) {
      req.onsuccess = () => {
        if (mode === 'readwrite') notifyWrite();
        resolve(req.result);
      };
      req.onerror = () => reject(req.error);
    } else {
      transaction.oncomplete = () => {
        if (mode === 'readwrite') notifyWrite();
        resolve(undefined as unknown as T);
      };
      transaction.onerror = () => reject(transaction.error);
    }
  });
}

let onWriteCallback: (() => void) | null = null;

export function registerOnWrite(cb: () => void) {
  onWriteCallback = cb;
}

export function notifyWrite() {
  if (onWriteCallback) {
    onWriteCallback();
  }
}
