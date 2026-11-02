import { FileAttachment } from '../shared/types';

const DOCUMENTS_STORAGE_KEY = 'jobfill_documents';
const LEGACY_DOCUMENTS_STORAGE_KEY = 'applypilot_documents';

export interface ResumeVariant {
  id: string;
  name: string;
  rolePattern: string; // e.g. "React", "Rust", "Backend"
  file: FileAttachment;
}

export interface DocumentCollection {
  defaultResume?: FileAttachment;
  resumeVariants: ResumeVariant[];
  defaultCoverLetter?: FileAttachment;
  coverLetterTemplates: { id: string; name: string; body: string }[];
}

const DEFAULT_TEMPLATES = [
  {
    id: 'standard',
    name: 'Standard Template',
    body: 'Dear {{company}} Team,\n\nI am writing to express my strong interest in the {{role}} role. With my background in software engineering, especially focusing on {{topSkills}}, I am confident that I can make a meaningful impact.\n\n{{experienceSummary}}\n\nThank you for your consideration,\n{{candidateName}}'
  }
];

export async function getDocuments(): Promise<DocumentCollection> {
  const defaultCollection: DocumentCollection = {
    resumeVariants: [],
    coverLetterTemplates: DEFAULT_TEMPLATES
  };

  if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
    return new Promise((resolve) => {
      chrome.storage.local.get([DOCUMENTS_STORAGE_KEY, LEGACY_DOCUMENTS_STORAGE_KEY], (result) => {
        const docs = result[DOCUMENTS_STORAGE_KEY] || result[LEGACY_DOCUMENTS_STORAGE_KEY];
        if (docs && !result[DOCUMENTS_STORAGE_KEY] && result[LEGACY_DOCUMENTS_STORAGE_KEY]) {
          chrome.storage.local.set({ [DOCUMENTS_STORAGE_KEY]: docs });
        }
        resolve({
          ...defaultCollection,
          ...docs
        });
      });
    });
  }

  const data =
    localStorage.getItem(DOCUMENTS_STORAGE_KEY) || localStorage.getItem(LEGACY_DOCUMENTS_STORAGE_KEY);
  if (!data) return defaultCollection;
  try {
    const parsed = JSON.parse(data);
    if (!localStorage.getItem(DOCUMENTS_STORAGE_KEY) && localStorage.getItem(LEGACY_DOCUMENTS_STORAGE_KEY)) {
      localStorage.setItem(DOCUMENTS_STORAGE_KEY, data);
    }
    return {
      ...defaultCollection,
      ...parsed
    };
  } catch {
    return defaultCollection;
  }
}

export async function saveDocuments(docs: DocumentCollection): Promise<void> {
  if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
    return new Promise((resolve) => {
      chrome.storage.local.set({ [DOCUMENTS_STORAGE_KEY]: docs }, () => {
        resolve();
      });
    });
  }
  localStorage.setItem(DOCUMENTS_STORAGE_KEY, JSON.stringify(docs));
}
