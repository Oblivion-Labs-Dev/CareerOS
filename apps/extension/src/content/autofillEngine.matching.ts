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
    'non-veteran'
  ],
  "no, i don't have a disability": [
    "i don't have a disability",
    'no disability',
    'do not have a disability'
  ],
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
  const text = normalizeMatchText(optionText);
  const valLower = normalizeMatchText(value);
  if (!text || !valLower) return false;
  if (text === valLower) return true;
  if (matchesStateOption(text, valLower)) return true;
  if (pronounSetsMatch(text, valLower)) return true;
  if (isSynonymMatch(text, valLower)) return true;
  if (isPreferNotToAnswer(valLower) && /just use (my )?name/i.test(text)) return true;
  if (matchesLocationOption(text, value)) return true;
  if (valLower.length >= 4 && text.includes(valLower)) return true;
  return false;
}
