/**
 * Normalizes a question string by converting to lowercase, removing punctuation,
 * and collapsing multiple spaces to prepare it for fuzzy matching.
 */
export function normalizeQuestionText(text: string | null | undefined): string {
  if (!text || typeof text !== 'string') return '';
  return text
    .toLowerCase()
    .replace(/[.,\/#!$%\^&\*;:{}=\-_`~()?]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Removes company-specific noise (like "at Oblivion Labs") from the question text.
 */
export function removeCompanyNoise(text: string | null | undefined, companyName?: string | null): string {
  if (!text || typeof text !== 'string') return '';
  let cleaned = text;
  if (companyName && typeof companyName === 'string') {
    const escaped = companyName.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&');
    const regex = new RegExp(`\\bat\\s+${escaped}\\b|\\bfor\\s+${escaped}\\b`, 'gi');
    cleaned = cleaned.replace(regex, '');
  }
  // Generic company patterns
  cleaned = cleaned.replace(/\bat\s+our\s+company\b|\bat\s+this\s+company\b/gi, '');
  return cleaned;
}
