import { matchesStateOption, matchesLocationOption } from '../shared/usStates';

export const SYNONYMS: Record<string, string[]> = {
  'united states': ['us', 'usa', 'united states of america', 'u.s.a.', 'u.s.'],
  'united kingdom': ['uk', 'u.k.', 'great britain', 'gb'],
  yes: ['y', 'true', 'authorized', 'checked', 'agree', 'allow'],
  no: ['n', 'false', 'denied', 'disagree', 'non hispanic', 'not hispanic/latino', 'not hispanic'],
  'prefer not to answer': [
    'choose not to disclose',
    "i don't wish to answer",
    'i do not wish to answer',
    'decline to self-identify',
    'decline to answer',
    'prefer not to say',
    'do not wish to answer'
  ],
  'i am not a protected veteran': [
    'not a protected veteran',
    'non veteran',
    'non-veteran',
    'i am not a protected veteran.'
  ],
  "no, i don't have a disability": [
    "i don't have a disability",
    'no disability',
    'do not have a disability',
    'no, i do not have a disability and have not had one in the past',
    'no, i do not have a disability and have not had one in the past.'
  ],
  male: ['man'],
  female: ['woman'],
  'not hispanic or latino': ['no', 'not hispanic/latino', 'not hispanic', 'non hispanic'],
  'asian (not hispanic or latino)': ['south asian', 'asian'],
  'no - i do not consent to receiving text messages': [
    'no - i do not consent',
    'do not consent to receiving text messages',
    'decline text messages'
  ],
  'just use my name': ['prefer not to say', 'prefer not to answer', 'decline to answer'],
  'he/him/his': ['he him his', 'him his he', 'him/his/he', 'he, him, his']
};

const PREFER_NOT_TO_ANSWER_RE =
  /prefer not to (answer|say)|choose not to disclose|don'?t wish to answer|do not wish to answer|decline to (self-)?identify|decline to answer/i;

export function normalizeMatchText(text: string): string {
  return text.toLowerCase().trim().replace(/\s+/g, ' ');
}

export function isPreferNotToAnswer(text: string): boolean {
  const normalized = normalizeMatchText(text);
  if (PREFER_NOT_TO_ANSWER_RE.test(normalized)) return true;
  return SYNONYMS['prefer not to answer'].some(
    (phrase) => normalized === phrase || normalized.includes(phrase)
  );
}

/** Token-set match so "He/him/his" matches Rippling options like "him his he". */
export function pronounSetsMatch(a: string, b: string): boolean {
  const tokens = (text: string) =>
    text
      .toLowerCase()
      .replace(/[^a-z\s/]/g, ' ')
      .split(/[\s/]+/)
      .filter(Boolean)
      .sort();
  const left = tokens(a);
  const right = tokens(b);
  if (left.length < 2 || right.length < 2) return false;
  if (left.length !== right.length) return false;
  return left.every((token, index) => token === right[index]);
}

/** Profile pronouns → value to select on ATS forms (e.g. Rippling). */
export function resolvePronounFillValue(pronouns?: string): string {
  const raw = pronouns?.trim() || '';
  if (!raw) return '';
  if (isPreferNotToAnswer(raw)) return 'Just use my name';
  return raw;
}

export function isSynonymMatch(opt: string, val: string): boolean {
  const o = normalizeMatchText(opt);
  const v = normalizeMatchText(val);
  if (o === v) return true;

  if (isPreferNotToAnswer(o) && isPreferNotToAnswer(v)) return true;

  for (const [canonical, list] of Object.entries(SYNONYMS)) {
    if (o === canonical && list.includes(v)) return true;
    if (v === canonical && list.includes(o)) return true;
    if (list.includes(o) && list.includes(v)) return true;
  }

  const shorter = o.length <= v.length ? o : v;
  const longer = o.length <= v.length ? v : o;
  if (shorter.length >= 4 && longer.includes(shorter)) return true;

  return false;
}

export function matchesRadioOption(optionLabel: string, value: string): boolean {
  const label = normalizeMatchText(optionLabel);
  const val = normalizeMatchText(value);
  if (!label || !val) return false;
  if (label === val) return true;
  if (isSynonymMatch(label, val)) return true;
  if (label.startsWith(`${val} `) || label.startsWith(`${val} -`)) return true;
  if (val.length >= 12 && label.includes(val)) return true;
  return false;
}

export function matchesCustomOption(optionText: string, value: string): boolean {
  return scoreSelectOptionMatch(optionText, value) >= 75;
}

/** Score how well a dropdown option matches a profile value (0 = no match). */
export function scoreSelectOptionMatch(optionText: string, profileValue: string): number {
  const text = normalizeMatchText(optionText);
  const val = normalizeMatchText(profileValue);
  if (!text || !val) return 0;
  if (text === val) return 100;

  if (matchesStateOption(text, val)) return 95;
  if (pronounSetsMatch(text, val)) return 95;
  if (isSynonymMatch(text, val)) {
    if (text.includes(val) && val.length >= 10) return 92;
    if (val.includes(text) && text.length >= 10) return 90;
    return 85;
  }
  if (isPreferNotToAnswer(val) && /just use (my )?name/i.test(text)) return 85;
  if (matchesLocationOption(text, profileValue)) return 80;

  if (val.length >= 8 && text.includes(val)) return 55;
  if (text.length >= 8 && val.includes(text)) return 50;
  if (val.length >= 4 && text.startsWith(val)) return 45;

  return 0;
}

export function pickBestMatchingOptionText(options: string[], profileValue: string): string | undefined {
  let best: { text: string; score: number } | undefined;

  for (const option of options) {
    const trimmed = option.replace(/\s+/g, ' ').trim();
    if (!trimmed) continue;
    const score = scoreSelectOptionMatch(trimmed, profileValue);
    if (score <= 0) continue;
    if (!best || score > best.score || (score === best.score && trimmed.length > best.text.length)) {
      best = { text: trimmed, score };
    }
  }

  return best?.text;
}
