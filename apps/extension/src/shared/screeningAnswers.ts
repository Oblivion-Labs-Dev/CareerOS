import { ScreeningAnswer, UserProfile } from './types';
import { normalizeQuestionText, removeCompanyNoise } from '../learning/questionNormalizer';
import { stringSimilarity } from '../learning/fuzzyMatcher';
import { SCREENING_PROFILE_FIELD_LINKS } from './screeningAnswerProfile';

/** Snap / common ATS yes-no screening questions saved on profile. */
export const DEFAULT_SCREENING_ANSWERS: ScreeningAnswer[] = [
  {
    id: 'us-work-authorization',
    question: 'Are you authorized to work in the U.S.?',
    answer: 'Yes',
    matchPatterns: [
      'authorized to work in the us',
      'authorized to work in the united states',
      'legally authorized to work',
      'legally authorized to work in the country',
      'country/region you are applying',
      'u\\.s\\. work authorization',
      'are you authorized to work in the united states'
    ]
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
    question: 'Will you now or in the future require a visa sponsorship?',
    answer: 'Yes',
    matchPatterns: [
      'require a visa sponsorship',
      'now or in the future require.*visa sponsorship',
      'now or in the future require.*sponsorship',
      'need.*sponsor you for a visa',
      'visa sponsorship',
      'sponsor you for a visa',
      'immigration-related employment benefit',
      'require.*company.*sponsorship',
      'require.*sponsorship.*immigration',
      'commence.*sponsor.*immigration case',
      'employment-based visa status',
      'qualtrics.*sponsor',
      'require sponsorship from anduril',
      'sponsorship from anduril'
    ]
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
  },
  {
    id: 'bachelors-cs-engineering-experience',
    question:
      "Do you have a Bachelor's Degree in Computer Science or related technical field AND 4+ years technical engineering experience with coding in languages including, but not limited to, C, C++, C#, Java, JavaScript, or Python?",
    answer: 'Yes',
    matchPatterns: [
      "bachelor's degree in computer science",
      'related technical field and 4\\+ years technical engineering',
      'technical engineering experience with coding',
      'c, c\\+\\+, c#, java, javascript, or python'
    ]
  },
  {
    id: 'ms-minimum-qualifications-ack',
    question:
      'As part of the online application process you were asked whether you possess certain minimum required qualifications for the role to which you are applying.',
    answer: 'Yes',
    matchPatterns: [
      'minimum required qualifications for the role',
      'answered these questions accurately',
      'do not currently meet the required qualifications'
    ]
  },
  {
    id: 'ms-data-privacy-notice',
    question: 'By checking this you agree to the Microsoft Data Privacy Notice (DPN).',
    answer: 'Yes',
    matchPatterns: ['data privacy notice', 'microsoft data privacy', '\\bdpn\\b']
  },
  {
    id: 'ms-candidate-code-of-conduct',
    question:
      'By checking this, you affirm that you have familiarized yourself with the Microsoft recruiting process and agree to the candidate code of conduct.',
    answer: 'Yes',
    matchPatterns: [
      'candidate code of conduct',
      'microsoft recruiting process',
      'familiarized yourself with the microsoft recruiting'
    ]
  },
  {
    id: 'gender-identity',
    question: 'How would you describe your gender identity?',
    answer: 'Man',
    matchPatterns: ['gender identity', 'describe your gender']
  },
  {
    id: 'transgender-identity',
    question: 'Do you identify as transgender?',
    answer: 'No',
    matchPatterns: ['identify as transgender', 'transgender']
  },
  {
    id: 'racial-ethnic-background',
    question: 'How would you describe your racial/ethnic background?',
    answer: 'South Asian',
    matchPatterns: [
      'racial/ethnic background',
      'racial ethnic background',
      'describe your racial',
      'ethnic background'
    ]
  },
  {
    id: 'sexual-orientation',
    question: 'How would you describe your sexual orientation?',
    answer: 'Heterosexual',
    matchPatterns: ['sexual orientation', 'describe your sexual']
  },
  {
    id: 'legal-age-to-work',
    question: 'Are you of legal age to work in the country in which this position is based?',
    answer: 'Yes',
    matchPatterns: ['legal age to work', 'of legal age to work']
  },
  {
    id: 'at-least-18-years-old',
    question: 'Are you at least 18 years old?',
    answer: 'Yes',
    matchPatterns: ['at least 18 years old', 'at least 18', '18 years old']
  },
  {
    id: 'background-check-willing',
    question: 'Are you willing to undergo a background check as part of this hiring process?',
    answer: 'Yes',
    matchPatterns: ['background check', 'undergo a background check']
  },
  {
    id: 'government-employment',
    question:
      'Are you currently or have you ever been a member of the military, a civilian employee, or an official of any government?',
    answer: 'No',
    matchPatterns: [
      'member of the military',
      'official of any government',
      'civilian employee.*government',
      'national, state, local, or foreign'
    ]
  },
  {
    id: 'security-clearance-eligibility',
    question:
      'Do you presently hold an active U.S. security clearance, or are you eligible to obtain and maintain a U.S. security clearance?',
    answer: 'No',
    matchPatterns: [
      'clearance eligibility',
      'eligible to obtain and maintain.*security clearance',
      'hold an active u\\.s\\. security clearance',
      'presently hold an active.*security clearance'
    ]
  },
  {
    id: 'past-clearance-level',
    question: 'If you have held a U.S. security clearance in the past, what clearance level have you held?',
    answer: 'N/A - have never held U.S. security clearance',
    matchPatterns: ['clearance level have you held', 'held a u\\.s\\. security clearance in the past']
  },
  {
    id: 'export-controls-protected-individual',
    question: 'Are you any of the following protected individual(s) as defined in the Immigration and Naturalization Act',
    answer: 'None of the above',
    matchPatterns: ['export controls', 'protected individual', '1324b\\(a\\)\\(3\\)', 'export-controlled']
  },
  {
    id: 'previously-applied-company',
    question: 'Have you previously applied to a position at this company?',
    answer: 'No',
    matchPatterns: ['previously applied', 'history with', 'history with anduril']
  },
  {
    id: 'employed-by-company',
    question: 'Have you ever been employed by this company or any company it has acquired?',
    answer: 'No',
    matchPatterns: ['employed by anduril', 'employed by', 'company that anduril has acquired', 'company that.*has acquired']
  },
  {
    id: 'government-conflict-of-interest',
    question:
      'Do you currently, or have you in the last 5 years, worked for the US government and had oversight over this company?',
    answer: 'No',
    matchPatterns: ['conflict of interest', 'oversight.*business', 'worked for the us government']
  },
  {
    id: 'how-heard-about-company',
    question: 'How did you hear about this company?',
    answer: 'LinkedIn',
    matchPatterns: ['how did you hear about']
  }
];

const MATCH_THRESHOLD = 0.52;

function labelMatchesScreening(normalizedLabel: string, entry: ScreeningAnswer): boolean {
  const normalizedQuestion = normalizeQuestionText(entry.question);
  if (!normalizedLabel || !normalizedQuestion) return false;

  if (entry.matchPatterns?.some((pattern) => new RegExp(pattern, 'i').test(normalizedLabel))) {
    return true;
  }

  const similarity = stringSimilarity(normalizedLabel, normalizedQuestion);
  if (similarity >= MATCH_THRESHOLD) return true;

  return false;
}

function resolveScreeningEntryAnswer(entry: ScreeningAnswer, profile: UserProfile): string {
  if (entry.id === 'us-work-authorization' && profile.workAuthorization?.trim()) {
    return profile.workAuthorization.trim();
  }
  if (entry.id === 'visa-sponsorship-needed' && profile.sponsorship?.trim()) {
    return profile.sponsorship.trim();
  }
  if (entry.id === 'gender-identity' && profile.gender?.trim()) {
    return profile.gender.trim();
  }
  if (entry.id === 'transgender-identity' && profile.transgender?.trim()) {
    return profile.transgender.trim();
  }
  if (entry.id === 'racial-ethnic-background' && profile.raceEthnicity?.trim()) {
    return profile.raceEthnicity.trim();
  }
  if (entry.id === 'sexual-orientation' && profile.sexualOrientation?.trim()) {
    return profile.sexualOrientation.trim();
  }
  return entry.answer;
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

  const patternMatches = answers.filter((entry) =>
    entry.matchPatterns?.some((pattern) => new RegExp(pattern, 'i').test(cleanedLabel))
  );
  if (patternMatches.length) {
    const bestPatternMatch = patternMatches.sort(
      (a, b) =>
        Math.max(...(b.matchPatterns || []).map((pattern) => pattern.length)) -
        Math.max(...(a.matchPatterns || []).map((pattern) => pattern.length))
    )[0];
    return resolveScreeningEntryAnswer(bestPatternMatch, profile);
  }

  for (const entry of answers) {
    if (labelMatchesScreening(cleanedLabel, entry)) {
      return resolveScreeningEntryAnswer(entry, profile);
    }
  }

  if (/authorized to work|legally authorized|work authorization/.test(cleanedLabel) && profile.workAuthorization?.trim()) {
    return profile.workAuthorization.trim();
  }
  if (
    /require a visa sponsorship|sponsor you for a visa|visa sponsorship|require.*sponsorship|immigration-related employment benefit|commence.*sponsor.*immigration|employment-based visa status/.test(
      cleanedLabel
    )
  ) {
    return profile.sponsorship?.trim() || undefined;
  }

  return undefined;
}

function slugifyQuestion(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 48);
}

/** Remember a new ATS question on the profile when autofill could not fill it. */
export function appendScreeningAnswerForLabel(
  profile: UserProfile,
  questionText: string,
  answer: string,
  canonicalKey?: 'workAuthorization' | 'sponsorship'
): UserProfile {
  const question = questionText.replace(/\*+$/, '').trim();
  if (!question || !answer.trim()) return profile;

  const existing = profile.screeningAnswers?.length
    ? profile.screeningAnswers
    : DEFAULT_SCREENING_ANSWERS.map((entry) => ({ ...entry }));

  const normalized = normalizeQuestionText(question);
  const alreadyKnown = existing.some((entry) => {
    const entryNorm = normalizeQuestionText(entry.question);
    return entryNorm === normalized || stringSimilarity(entryNorm, normalized) >= 0.82;
  });
  if (alreadyKnown) return profile;

  const pattern = normalized.replace(/\s+/g, ' ').slice(0, 80);
  const nextAnswers = [
    ...existing,
    {
      id: `learned-${slugifyQuestion(question) || 'field'}`,
      question,
      answer: answer.trim(),
      matchPatterns: [pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')]
    }
  ];

  const next = syncProfileFromScreeningAnswers({ ...profile, screeningAnswers: nextAnswers });
  if (canonicalKey === 'workAuthorization') next.workAuthorization = answer.trim();
  if (canonicalKey === 'sponsorship') next.sponsorship = answer.trim();
  return next;
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

export function mergeDefaultScreeningAnswers(existing?: ScreeningAnswer[]): ScreeningAnswer[] {
  return mergeScreeningAnswers(DEFAULT_SCREENING_ANSWERS, existing);
}

export function syncProfileFromScreeningAnswers(profile: UserProfile): UserProfile {
  let answers = mergeDefaultScreeningAnswers(profile.screeningAnswers).map((entry) => ({ ...entry }));

  for (const [screeningId, profileField] of Object.entries(SCREENING_PROFILE_FIELD_LINKS)) {
    const profileValue = profile[profileField]?.trim();
    if (!profileValue) continue;
    answers = answers.map((entry) =>
      entry.id === screeningId ? { ...entry, answer: profileValue } : entry
    );
  }

  const next: UserProfile = { ...profile, screeningAnswers: answers };
  const byId = new Map(answers.map((entry) => [entry.id, entry.answer]));

  for (const [screeningId, profileField] of Object.entries(SCREENING_PROFILE_FIELD_LINKS)) {
    const answer = byId.get(screeningId);
    if (answer?.trim()) {
      next[profileField] = answer.trim();
    }
  }

  return next;
}
