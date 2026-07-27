/** Jobscan-inspired local keyword overlap between job description and profile. */

import { UserProfile } from './types';

const STOP_WORDS = new Set([
  'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
  'from', 'as', 'is', 'was', 'are', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
  'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'shall',
  'can', 'need', 'dare', 'ought', 'used', 'that', 'this', 'these', 'those', 'i', 'you',
  'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who', 'whom', 'whose', 'where', 'when',
  'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some',
  'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
  'work', 'working', 'experience', 'years', 'year', 'role', 'team', 'company', 'job', 'position'
]);

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9+#.\s-]/g, ' ')
    .split(/\s+/)
    .filter((word) => word.length >= 2 && !STOP_WORDS.has(word));
}

function uniqueTokens(text: string): Set<string> {
  return new Set(tokenize(text));
}

function profileKeywords(profile: UserProfile): Set<string> {
  const parts = [
    profile.targetRole,
    profile.currentTitle,
    profile.yearsExperience,
    profile.fullName,
    profile.location,
    ...(profile.workExperience || []).flatMap((entry) => [
      entry.jobTitle,
      entry.company,
      entry.description
    ]),
    ...(profile.screeningAnswers || []).map((a) => a.answer)
  ];
  const blob = parts.filter(Boolean).join(' ');
  return uniqueTokens(blob);
}

export interface KeywordScanResult {
  score: number;
  matched: string[];
  missing: string[];
  totalJobKeywords: number;
}

export function scanJobKeywords(
  jobDescription: string,
  profile: UserProfile,
  maxKeywords = 24
): KeywordScanResult {
  const jobTokens = uniqueTokens(jobDescription);
  const profileTokens = profileKeywords(profile);

  const ranked = [...jobTokens]
    .filter((token) => token.length >= 3)
    .sort((a, b) => b.length - a.length);

  const jobKeywords = ranked.slice(0, maxKeywords);
  const matched: string[] = [];
  const missing: string[] = [];

  for (const keyword of jobKeywords) {
    const hit =
      profileTokens.has(keyword) ||
      [...profileTokens].some((p) => p.includes(keyword) || keyword.includes(p));
    if (hit) matched.push(keyword);
    else missing.push(keyword);
  }

  const total = jobKeywords.length || 1;
  const score = Math.round((matched.length / total) * 100);

  return {
    score,
    matched: matched.slice(0, 12),
    missing: missing.slice(0, 8),
    totalJobKeywords: jobKeywords.length
  };
}
