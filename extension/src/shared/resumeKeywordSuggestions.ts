import { UserProfile } from './types';

export interface ResumeKeywordSuggestion {
  keyword: string;
  reason: string;
  priority: 'high' | 'medium';
}

/** Free local suggestions from keyword scan gaps — no LLM required. */
export function buildResumeKeywordSuggestions(
  missingKeywords: string[],
  profile: UserProfile
): ResumeKeywordSuggestion[] {
  const skills = (Array.isArray(profile.skills) ? profile.skills : String(profile.skills || '').split(/[,;\n|]+/))
    .map((s: string) => s.trim().toLowerCase())
    .filter(Boolean);

  const suggestions: ResumeKeywordSuggestion[] = [];

  for (const keyword of missingKeywords.slice(0, 12)) {
    const lower = keyword.toLowerCase();
    const related = skills.find((s) => s.includes(lower) || lower.includes(s));
    suggestions.push({
      keyword,
      reason: related
        ? `Related skill "${related}" is on your profile — add "${keyword}" explicitly to bullets.`
        : `Job mentions "${keyword}" — add a bullet showing hands-on experience if true.`,
      priority: missingKeywords.indexOf(keyword) < 4 ? 'high' : 'medium'
    });
  }

  return suggestions;
}

export function formatResumeSuggestionsText(suggestions: ResumeKeywordSuggestion[]): string {
  if (!suggestions.length) return '';
  return suggestions
    .slice(0, 6)
    .map((s) => `• ${s.keyword}: ${s.reason}`)
    .join('\n');
}
