import { UserProfile } from '../shared/types';
import { APPLICATION_FIELD_DEFAULTS } from '../shared/applicationDefaults';
import { mergeWorkExperienceLists, resolveMostRecentEmployer } from '../shared/workExperience';
import {
  mergeScreeningAnswers,
  syncProfileFromScreeningAnswers,
  DEFAULT_SCREENING_ANSWERS
} from '../shared/screeningAnswers';

import { getServerDbUrl } from '../shared/apiConfig';
const PROFILE_STORAGE_KEY = 'jobfill_profile';
const LEGACY_PROFILE_STORAGE_KEY = 'applypilot_profile';

const PROFILE_STRING_KEYS: (keyof UserProfile)[] = [
  'firstName',
  'lastName',
  'fullName',
  'email',
  'phone',
  'location',
  'linkedin',
  'github',
  'portfolio',
  'workAuthorization',
  'sponsorship',
  'yearsExperience',
  'currentTitle',
  'currentCompany',
  'targetRole',
  'salaryExpectations',
  'pronouns',
  'gender',
  'raceEthnicity',
  'hispanic',
  'veteran',
  'disability',
  'smsConsent'
];

export function isExtensionContext(): boolean {
  try {
    return typeof chrome !== 'undefined' && !!chrome.runtime?.id;
  } catch {
    return false;
  }
}

export function mergeProfiles(
  primary: UserProfile | null | undefined,
  secondary: UserProfile | null | undefined
): UserProfile {
  const merged = createEmptyProfile();

  for (const key of PROFILE_STRING_KEYS) {
    const a = primary?.[key]?.trim() || '';
    const b = secondary?.[key]?.trim() || '';
    if (a || b) merged[key] = a || b;
  }

  if (primary?.customFields || secondary?.customFields) {
    merged.customFields = {
      ...(secondary?.customFields || {}),
      ...(primary?.customFields || {})
    };
  }

  merged.workExperience = mergeWorkExperienceLists(
    secondary?.workExperience,
    primary?.workExperience || []
  );

  merged.screeningAnswers = mergeScreeningAnswers(
    secondary?.screeningAnswers,
    primary?.screeningAnswers
  );

  return enrichProfile(syncProfileFromScreeningAnswers(merged));
}

async function readChromeProfile(): Promise<UserProfile | null> {
  if (!isExtensionContext() || !chrome.storage?.local) return null;
  return new Promise((resolve) => {
    chrome.storage.local.get([PROFILE_STORAGE_KEY, LEGACY_PROFILE_STORAGE_KEY], (result) => {
      const profile = result[PROFILE_STORAGE_KEY] || result[LEGACY_PROFILE_STORAGE_KEY] || null;
      if (profile && !result[PROFILE_STORAGE_KEY] && result[LEGACY_PROFILE_STORAGE_KEY]) {
        chrome.storage.local.set({ [PROFILE_STORAGE_KEY]: profile });
      }
      resolve(profile);
    });
  });
}

async function writeChromeProfile(profile: UserProfile): Promise<void> {
  if (!isExtensionContext() || !chrome.storage?.local) return;
  return new Promise((resolve) => {
    chrome.storage.local.set({ [PROFILE_STORAGE_KEY]: profile }, () => resolve());
  });
}

export async function fetchServerDb(): Promise<{
  profile?: UserProfile;
  documents?: { defaultResume?: UserProfile['resume']; defaultCoverLetter?: UserProfile['coverLetter'] };
} | null> {
  try {
    const res = await fetch(await getServerDbUrl());
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function pushProfileToServer(profile: UserProfile): Promise<boolean> {
  try {
    const db = await fetchServerDb();
    if (!db) return false;
    db.profile = profile;
    const res = await fetch(await getServerDbUrl(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(db)
    });
    return res.ok;
  } catch {
    return false;
  }
}

const EEO_CUSTOM_FIELD_LABEL_RE =
  /gender|sex\b|race|ethnicity|hispanic|latino|veteran|disability/i;

/** Drop legacy customFields copies now stored as first-class profile keys. */
function stripLegacyEeoCustomFields(profile: UserProfile): void {
  if (!profile.customFields) return;
  for (const key of Object.keys(profile.customFields)) {
    if (EEO_CUSTOM_FIELD_LABEL_RE.test(key)) {
      delete profile.customFields[key];
    }
  }
  if (Object.keys(profile.customFields).length === 0) {
    delete profile.customFields;
  }
}

export function enrichProfile(profile: UserProfile): UserProfile {
  const enriched: UserProfile = {
    ...profile,
    customFields: profile.customFields ? { ...profile.customFields } : undefined,
    screeningAnswers: profile.screeningAnswers?.length
      ? profile.screeningAnswers.map((entry) => ({ ...entry }))
      : DEFAULT_SCREENING_ANSWERS.map((entry) => ({ ...entry }))
  };

  stripLegacyEeoCustomFields(enriched);

  if (!enriched.firstName?.trim() && enriched.fullName?.trim()) {
    const parts = enriched.fullName.trim().split(/\s+/);
    enriched.firstName = parts[0] || '';
    enriched.lastName = parts.slice(1).join(' ') || enriched.lastName || '';
  }

  if (!enriched.fullName?.trim() && enriched.firstName?.trim()) {
    enriched.fullName = `${enriched.firstName} ${enriched.lastName || ''}`.trim();
  }

  if (!enriched.veteran?.trim()) enriched.veteran = APPLICATION_FIELD_DEFAULTS.veteran;
  if (!enriched.disability?.trim()) enriched.disability = APPLICATION_FIELD_DEFAULTS.disability;
  if (!enriched.smsConsent?.trim()) enriched.smsConsent = APPLICATION_FIELD_DEFAULTS.smsConsent;
  if (!enriched.gender?.trim()) enriched.gender = APPLICATION_FIELD_DEFAULTS.gender;
  if (!enriched.raceEthnicity?.trim()) enriched.raceEthnicity = APPLICATION_FIELD_DEFAULTS.raceEthnicity;
  if (!enriched.hispanic?.trim()) enriched.hispanic = APPLICATION_FIELD_DEFAULTS.hispanic;
  if (!enriched.currentCompany?.trim() && enriched.currentTitle?.trim()) {
    enriched.currentCompany = enriched.currentTitle;
  }

  const primaryJob = enriched.workExperience?.[0];
  if (primaryJob) {
    if (!enriched.currentTitle?.trim() && primaryJob.jobTitle?.trim()) {
      enriched.currentTitle = primaryJob.jobTitle;
    }
  if (!enriched.currentCompany?.trim() && primaryJob.company?.trim()) {
    enriched.currentCompany = primaryJob.company;
  } else if (!enriched.currentCompany?.trim()) {
    const recent = resolveMostRecentEmployer(enriched);
    if (recent) enriched.currentCompany = recent;
  }
    if (!enriched.location?.trim() && primaryJob.location?.trim()) {
      enriched.location = primaryJob.location;
    }
  }

  return enriched;
}

export function createEmptyProfile(): UserProfile {
  return {
    firstName: '',
    lastName: '',
    fullName: '',
    email: '',
    phone: '',
    location: '',
    linkedin: '',
    github: '',
    portfolio: '',
    workAuthorization: 'Yes',
    sponsorship: 'No',
    yearsExperience: '',
    currentTitle: '',
    targetRole: '',
    salaryExpectations: '',
    veteran: APPLICATION_FIELD_DEFAULTS.veteran,
    disability: APPLICATION_FIELD_DEFAULTS.disability,
    smsConsent: APPLICATION_FIELD_DEFAULTS.smsConsent,
    pronouns: '',
    gender: '',
    raceEthnicity: '',
    hispanic: '',
    workExperience: [],
    screeningAnswers: DEFAULT_SCREENING_ANSWERS.map((entry) => ({ ...entry }))
  };
}

export function hasContactProfileData(profile: UserProfile | null | undefined): boolean {
  if (!profile) return false;
  return Boolean(profile.firstName?.trim() && profile.lastName?.trim() && profile.email?.trim());
}

export function hasProfileData(profile: UserProfile | null | undefined): boolean {
  if (!profile) return false;
  return Boolean(
    profile.email?.trim() ||
    profile.firstName?.trim() ||
    profile.fullName?.trim() ||
    (profile.customFields && Object.values(profile.customFields).some((v) => v.trim() !== ''))
  );
}

export async function getProfile(): Promise<UserProfile | null> {
  const fromChrome = await readChromeProfile();
  const fromServer = (await fetchServerDb())?.profile ?? null;

  if (fromChrome && fromServer) return mergeProfiles(fromChrome, fromServer);
  if (fromChrome) return fromChrome;
  if (fromServer) return fromServer;

  if (!isExtensionContext()) return null;

  const data =
    localStorage.getItem(PROFILE_STORAGE_KEY) || localStorage.getItem(LEGACY_PROFILE_STORAGE_KEY);
  if (!data) return null;
  try {
    const profile = JSON.parse(data) as UserProfile;
    if (!localStorage.getItem(PROFILE_STORAGE_KEY) && localStorage.getItem(LEGACY_PROFILE_STORAGE_KEY)) {
      localStorage.setItem(PROFILE_STORAGE_KEY, data);
    }
    return profile;
  } catch {
    return null;
  }
}

export async function saveProfile(profile: UserProfile): Promise<void> {
  await writeChromeProfile(profile);
  await pushProfileToServer(profile);

  if (!isExtensionContext()) {
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
  }
}

export async function resolveProfileForAutofill(): Promise<UserProfile> {
  const { getDocuments, saveDocuments } = await import('../documents/documentStore');
  const { syncFromServer } = await import('../db/sync');

  await syncFromServer();

  const fromChrome = await readChromeProfile();
  const serverDb = await fetchServerDb();
  const profile = mergeProfiles(fromChrome, serverDb?.profile);
  await writeChromeProfile(profile);

  const docs = await getDocuments();
  if (serverDb?.documents?.defaultResume && !docs.defaultResume) {
    await saveDocuments({
      ...docs,
      defaultResume: serverDb.documents.defaultResume,
      defaultCoverLetter: serverDb.documents.defaultCoverLetter ?? docs.defaultCoverLetter
    });
  }

  const finalDocs = await getDocuments();
  profile.resume = finalDocs.defaultResume ?? serverDb?.documents?.defaultResume;
  profile.coverLetter = finalDocs.defaultCoverLetter ?? serverDb?.documents?.defaultCoverLetter;

  return enrichProfile(profile);
}

export async function clearProfile(): Promise<void> {
  if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
    return new Promise((resolve) => {
      chrome.storage.local.remove([PROFILE_STORAGE_KEY, LEGACY_PROFILE_STORAGE_KEY], () => {
        resolve();
      });
    });
  }
  localStorage.removeItem(PROFILE_STORAGE_KEY);
  localStorage.removeItem(LEGACY_PROFILE_STORAGE_KEY);
}
