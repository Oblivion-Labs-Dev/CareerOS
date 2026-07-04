import { ScreeningAnswer, UserProfile } from './types';
import { normalizeQuestionText, removeCompanyNoise } from '../learning/questionNormalizer';
import { stringSimilarity } from '../learning/fuzzyMatcher';

/** Snap / common ATS yes-no screening questions saved on profile. */
export const DEFAULT_SCREENING_ANSWERS: ScreeningAnswer[] = [
  {
    id: 'us-work-authorization',
    question: 'Are you authorized to work in the U.S.?',
    answer: 'Yes',
    matchPatterns: ['authorized to work in the us', 'authorized to work in the united states']
  },
  {
    id: 'spouse-visa-status',
    question:
      'Is your current U.S. work authorization based on your status as a spouse of an H-1B, L-1, or E-1/E-2/E-3 visa holder?',
    answer: 'No',
    matchPatterns: ['spouse of an h-1b', 'spouse of an h1b', 'e-1/e-2/e-3 visa holder']
  },
  {
    id: 'visa-sponsorship-needed',
    question:
      'Will you need Snap to sponsor you for a visa to work legally in the United States, now or in the future?',
    answer: 'Yes',
    matchPatterns: ['need.*sponsor you for a visa', 'visa sponsorship', 'sponsor you for a visa']
  },
  {
    id: 'snap-eligibility-followup',
    question: 'Did you answer "no" to Question 1 and/or "yes" to question 2 or 3?',
    answer: 'No',
    matchPatterns: ['answered no to question 1', 'yes to question 2 or 3']
  },
  {
    id: 'relocate-to-job-location',
    question:
      'Do you currently live in or are you able to relocate to the location this job is advertised in?',
    answer: 'Yes',
    matchPatterns: ['relocate to the location', 'live in or are you able to relocate']
  },
  {
    id: 'office-attendance-commitment',
    question:
      'Are you able to commit to coming into the office as advertised on the job description?',
    answer: 'Yes',
    matchPatterns: ['commit to coming into the office', '4+ days a week']
  },
  {
    id: 'meets-minimum-experience',
    question:
      'Can you confirm that you meet the minimum qualification for years of professional work experience for this role?',
    answer: 'Yes',
    matchPatterns: ['meet the minimum qualification', 'minimum qualification for years']
  },
  {
    id: 'big-four-employment',
    question: 'Are you a current or former (prior 18 months) employee of EY, PwC, Deloitte or KPMG?',
    answer: 'No',
    matchPatterns: ['employee of ey', 'pwc', 'deloitte', 'kpmg']
  }
];

const MATCH_THRESHOLD = 0.52;

function labelMatchesScreening(normalizedLabel: string, entry: ScreeningAnswer): boolean {
  const normalizedQuestion = normalizeQuestionText(entry.question);
  if (!normalizedLabel || !normalizedQuestion) return false;

  const similarity = stringSimilarity(normalizedLabel, normalizedQuestion);
  if (similarity >= MATCH_THRESHOLD) return true;

  if (entry.matchPatterns?.some((pattern) => new RegExp(pattern, 'i').test(normalizedLabel))) {
    return true;
  }

  return false;
}

export function matchScreeningAnswer(
  label: string,
  profile: UserProfile,
  company?: string
): string | undefined {
  const cleanedLabel = normalizeQuestionText(removeCompanyNoise(label, company));
  if (!cleanedLabel) return undefined;

  const answers = profile.screeningAnswers?.length
    ? profile.screeningAnswers
    : DEFAULT_SCREENING_ANSWERS;

  for (const entry of answers) {
    if (labelMatchesScreening(cleanedLabel, entry)) {
      return entry.answer;
    }
  }

  if (/authorized to work/.test(cleanedLabel) && profile.workAuthorization?.trim()) {
    return profile.workAuthorization.trim();
  }
  if (/sponsor you for a visa|visa sponsorship|require.*sponsorship/.test(cleanedLabel)) {
    return profile.sponsorship?.trim() || undefined;
  }

  return undefined;
}

export function mergeScreeningAnswers(
  existing: ScreeningAnswer[] | undefined,
  incoming: ScreeningAnswer[] | undefined
): ScreeningAnswer[] {
  if (!incoming?.length) return existing || [];
  if (!existing?.length) return incoming;

  const byId = new Map(existing.map((entry) => [entry.id, entry]));
  for (const entry of incoming) {
    byId.set(entry.id, { ...byId.get(entry.id), ...entry });
  }
  return [...byId.values()];
}

export function syncProfileFromScreeningAnswers(profile: UserProfile): UserProfile {
  const answers = profile.screeningAnswers?.length
    ? profile.screeningAnswers
    : DEFAULT_SCREENING_ANSWERS;

  const byId = new Map(answers.map((entry) => [entry.id, entry.answer]));
  const next = { ...profile };

  if (byId.get('us-work-authorization')) {
    next.workAuthorization = byId.get('us-work-authorization')!;
  }
  if (byId.get('visa-sponsorship-needed')) {
    next.sponsorship = byId.get('visa-sponsorship-needed')!;
  }

  return next;
}
