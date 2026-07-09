import { ScannedField, getLabelText, getFieldGroupQuestion } from './domScanner';
import { UserProfile } from '../shared/types';
import { APPLICATION_FIELD_DEFAULTS } from '../shared/applicationDefaults';
import {
  resolveDisabilitySelectValue,
  resolveEthnicGroupSelectValue,
  resolveGenderSelectValue,
  resolveRaceSelectValue,
  resolveVeteranSelectValue
} from '../shared/eeoFillValues';
import { stringSimilarity } from '../learning/fuzzyMatcher';
import { resolvePronounFillValue } from './autofillEngine.matching';
import { preferredStateFillValue, parseLocationParts } from '../shared/usStates';
import { resolveMostRecentEmployer } from '../shared/workExperience';
import { matchScreeningAnswer } from '../shared/screeningAnswers';

const OPTION_LABEL_RE = /^(yes|no|true|false)$/i;
const MAX_GROUP_QUESTION_LENGTH = 600;

/** Yes/no or long-form ATS screening prompts — not address/state fields. */
export function isScreeningQuestionLabel(text: string): boolean {
  const normalized = text.replace(/\*+$/, '').replace(/\s+/g, ' ').trim();
  if (!normalized) return false;
  if (/^(are you|do you|have you|will you|did you|can you|please indicate)\b/i.test(normalized)) {
    return true;
  }
  if (
    normalized.length > 80 &&
    /(are you|do you|have you|will you|member of|belong to|authorized|sponsorship|veteran|disability|government|military)/i.test(
      normalized
    )
  ) {
    return true;
  }
  if (/\?/.test(normalized) && /(are you|do you|have you|will you|willing to|require)/i.test(normalized)) {
    return true;
  }
  return false;
}

export const RIPPLING_DATA_INPUT_MAP: Record<string, (profile: UserProfile) => string | undefined> = {
  first_name: (p) => p.firstName,
  last_name: (p) => p.lastName,
  email: (p) => p.email,
  phone_number: (p) => p.phone,
  linkedin_link: (p) => p.linkedin,
  website_link: (p) => p.portfolio,
  location: (p) => p.location,
  current_company: (p) => p.currentCompany || p.currentTitle,
  pronouns: (p) => resolvePronounFillValue(p.pronouns)
};

export const RIPPLING_DATA_INPUT_TO_CANONICAL: Record<string, string> = {
  first_name: 'firstName',
  last_name: 'lastName',
  email: 'email',
  phone_number: 'phone',
  linkedin_link: 'linkedin',
  website_link: 'portfolio',
  location: 'location',
  current_company: 'currentCompany',
  pronouns: 'pronouns'
};

export function getRipplingDataInput(element: HTMLElement): string {
  return (
    element.getAttribute('data-input') ||
    element.getAttribute('data-testid')?.replace(/^input-/, '') ||
    ''
  );
}

export function resolveFieldLabel(field: ScannedField, doc?: Document): string {
  const direct = (field.labelText || '').trim();
  if (direct && !OPTION_LABEL_RE.test(direct) && !/^(search|textbox|select\.\.\.|select)$/i.test(direct)) {
    return direct.replace(/\*+$/, '').trim();
  }

  const rootDoc =
    doc ??
    field.element?.ownerDocument ??
    (typeof globalThis.document !== 'undefined' ? globalThis.document : undefined);

  if (rootDoc && (field.type === 'radio' || field.type === 'checkbox')) {
    const groupQuestion = getFieldGroupQuestion(field.element, rootDoc);
    if (groupQuestion) return groupQuestion;
  }

  if (rootDoc) {
    const fromElement = getLabelText(field.element, rootDoc);
    if (
      fromElement &&
      !OPTION_LABEL_RE.test(fromElement) &&
      !/^(search|textbox|select\.\.\.|select)$/i.test(fromElement)
    ) {
      return fromElement.replace(/\*+$/, '').trim();
    }
  }

  let node: HTMLElement | null = field.element.parentElement;
  while (node && node.tagName !== 'BODY') {
    for (const child of Array.from(node.children)) {
      if (child === field.element || child.contains(field.element)) continue;
      const text = child.textContent?.replace(/\s+/g, ' ').trim() || '';
      if (
        text.length > 12 &&
        text.length < MAX_GROUP_QUESTION_LENGTH &&
        !OPTION_LABEL_RE.test(text) &&
        !/^(search|textbox|select\.\.\.|select)$/i.test(text)
      ) {
        return text.replace(/\*+$/, '').trim();
      }
    }
    node = node.parentElement;
  }

  const placeholder = field.placeholder?.trim();
  if (placeholder && placeholder.length > 2) return placeholder;

  return direct || field.name || '';
}

function pickBestCustomField(label: string, profile: UserProfile): string {
  if (!profile.customFields || !label) return '';
  let bestValue = '';
  let bestScore = 0;

  for (const [customLabel, customVal] of Object.entries(profile.customFields)) {
    if (!customVal?.trim()) continue;
    const score = stringSimilarity(label.toLowerCase(), customLabel.toLowerCase());
    if (score > bestScore) {
      bestScore = score;
      bestValue = customVal;
    }
  }

  return bestScore >= 0.55 ? bestValue : '';
}

export const RIPPLING_DATA_INPUT_KEYS = Object.keys(RIPPLING_DATA_INPUT_MAP);

export function hasRipplingContactDataInput(field: ScannedField): boolean {
  const dataInput =
    field.element.getAttribute('data-input') ||
    field.element.getAttribute('data-testid')?.replace(/^input-/, '') ||
    '';
  return !!(dataInput && dataInput in RIPPLING_DATA_INPUT_MAP);
}

function valueFromRipplingAttribute(field: ScannedField, profile: UserProfile): string {
  const el = field.element;
  const dataInput = el.getAttribute('data-input') || el.getAttribute('data-testid')?.replace(/^input-/, '') || '';
  if (!dataInput) return '';

  const resolver = RIPPLING_DATA_INPUT_MAP[dataInput];
  if (resolver) return resolver(profile)?.trim() || '';

  return '';
}

function parseLocationPartsFromProfile(location: string): { city: string; state: string; zip: string } {
  return parseLocationParts(location);
}

/** Phone dial-code dropdowns (e.g. Qualtrics "Country" field above Phone). */
export function isPhoneCountryLabel(label: string): boolean {
  const normalized = label.replace(/\*+$/, '').replace(/\s+/g, ' ').trim().toLowerCase();
  if (/country code|dial code|phone country|calling code/.test(normalized)) return true;
  return normalized === 'country';
}

export function resolvePhoneCountryFillValue(profile: UserProfile): string {
  return profile.phoneCountryCode?.trim() || APPLICATION_FIELD_DEFAULTS.phoneCountryCode;
}

function valueFromLabelHeuristics(label: string, profile: UserProfile): string {
  const l = label.toLowerCase();
  const { city, state, zip } = parseLocationPartsFromProfile(profile.location || '');

  if (isScreeningQuestionLabel(label)) {
    return matchScreeningAnswer(label, profile) || '';
  }

  if (/first\s*name|given\s*name/.test(l)) return profile.firstName;
  if (/last\s*name|family\s*name|surname/.test(l)) return profile.lastName;
  if (/legal\s*name|full\s*name/.test(l)) {
    return profile.fullName || `${profile.firstName || ''} ${profile.lastName || ''}`.trim();
  }
  if (/preferred\s*name|name\s*you\s*go\s*by/.test(l)) {
    return profile.preferredName || profile.fullName;
  }
  if (/email/.test(l)) return profile.email;
  if (/phone|mobile|telephone/.test(l)) return profile.phone;
  if (/address\s*line\s*2|apt|suite|unit\b/.test(l)) return '';
  if (/^address$/i.test(l.trim()) || (/^address\b/i.test(l) && !/line\s*2/.test(l))) {
    return profile.customFields?.addressLine1 || profile.customFields?.street || '';
  }
  if (/address\s*line\s*1|street|mailing\s*address/.test(l)) {
    return profile.customFields?.addressLine1 || profile.customFields?.street || '';
  }
  if (/\bcity\b/.test(l)) return profile.customFields?.city || city || profile.location;
  if ((/\bstate\b|province/.test(l)) && !isScreeningQuestionLabel(label)) {
    return preferredStateFillValue(profile.customFields?.state || state);
  }
  if (/zip|postal/.test(l)) return profile.customFields?.zip || profile.customFields?.postalCode || zip;
  if (isPhoneCountryLabel(label)) return resolvePhoneCountryFillValue(profile);
  if (/country|region of residence/.test(l)) return profile.customFields?.country || 'United States';
  if (/location|residence|work location|where.*live|currently located|where.*located/.test(l)) return profile.location;
  if (/linkedin/.test(l)) return profile.linkedin;
  if (/website|portfolio/.test(l)) return profile.portfolio;
  if (/github/.test(l)) return profile.github;
  if (/most\s+recently\s+worked|recent\s+employer|last\s+(?:company|employer)|where.*you.*worked/i.test(l)) {
    return resolveMostRecentEmployer(profile);
  }
  if (/current\s*company|employer/.test(l)) return resolveMostRecentEmployer(profile);
  if (/pronoun/.test(l)) return resolvePronounFillValue(profile.pronouns);
  if (/hispanic|latino|ethnic group/.test(l) && !/race/.test(l)) {
    return resolveEthnicGroupSelectValue(profile.hispanic);
  }
  if (/\bgender\b/.test(l) && !/identity|transgender|sexual/.test(l)) {
    return resolveGenderSelectValue(profile.gender);
  }
  if (/transgender/.test(l)) return profile.transgender || APPLICATION_FIELD_DEFAULTS.transgender;
  if (/sexual orientation/.test(l)) {
    return profile.sexualOrientation || APPLICATION_FIELD_DEFAULTS.sexualOrientation;
  }
  if (/protected veteran|veteran status|categories of protected veterans/.test(l)) {
    return resolveVeteranSelectValue(profile.veteran);
  }
  if (/disability|form cc-305|cc-305/.test(l)) {
    return resolveDisabilitySelectValue(profile.disability);
  }
  if (/veteran/.test(l)) return resolveVeteranSelectValue(profile.veteran);
  if (/race|ethnicity/.test(l)) return resolveRaceSelectValue(profile.raceEthnicity, profile.hispanic);
  if (/text\s*message|sms|consent/.test(l)) return profile.smsConsent || APPLICATION_FIELD_DEFAULTS.smsConsent;
  if (/years.*experience|experience\s*level/.test(l)) return profile.yearsExperience;
  if (/salary|compensation/.test(l)) return profile.salaryExpectations;
  if (/authorized|right\s*to\s*work|legally authorized|work authorization/.test(l)) return profile.workAuthorization;
  if (/sponsor|visa|immigration-related employment benefit|require.*sponsorship/.test(l)) return profile.sponsorship;
  return '';
}

export function inferRemainingValue(
  field: ScannedField,
  profile: UserProfile,
  matchedKey?: string,
  company?: string
): { value: string; reason: string; canonicalKey?: string } {
  const label = resolveFieldLabel(field);

  const fromScreening = matchScreeningAnswer(label, profile, company);
  if (fromScreening && (field.type === 'select' || field.type === 'radio' || field.type === 'checkbox')) {
    return {
      value: fromScreening,
      reason: 'Profile screening answer',
      canonicalKey: 'customQuestion'
    };
  }

  const fromRippling = valueFromRipplingAttribute(field, profile);
  if (fromRippling) {
    return { value: fromRippling, reason: 'Rippling data-input attribute mapping' };
  }

  const fromLabel = valueFromLabelHeuristics(label, profile);
  if (fromLabel) {
    const isContactInference =
      /phone|email|location|linkedin|website|portfolio|github|first\s*name|last\s*name|company/.test(
        label.toLowerCase()
      );
    if (!(field.type === 'select' && isContactInference && !hasRipplingContactDataInput(field))) {
      return { value: fromLabel, reason: `Inferred from label "${label}"` };
    }
  }

  const fromCustom = pickBestCustomField(label, profile);
  if (fromCustom) {
    return { value: fromCustom, reason: `Fuzzy custom field match for "${label}"`, canonicalKey: 'customQuestion' };
  }

  if (matchedKey && matchedKey in APPLICATION_FIELD_DEFAULTS) {
    return {
      value: APPLICATION_FIELD_DEFAULTS[matchedKey as keyof typeof APPLICATION_FIELD_DEFAULTS],
      reason: 'Application default answer',
      canonicalKey: matchedKey
    };
  }

  if (field.type === 'radio') {
    const options = field.options || [];
    const noOption = options.find((o) => /do not consent|^\s*no\b/i.test(o));
    if (noOption) {
      return { value: noOption, reason: 'Default radio: decline/no option', canonicalKey: 'smsConsent' };
    }
  }

  if ((field.type === 'text' || field.type === 'textarea') && field.placeholder && !/^(search|\.\.\.)$/i.test(field.placeholder)) {
    const fromPlaceholder = valueFromLabelHeuristics(field.placeholder, profile);
    if (fromPlaceholder) {
      return { value: fromPlaceholder, reason: `Inferred from placeholder "${field.placeholder}"` };
    }
  }

  return { value: '', reason: 'No inference available' };
}

export function isFillableFieldType(type: ScannedField['type']): boolean {
  return ['text', 'textarea', 'select', 'radio', 'checkbox', 'file'].includes(type);
}
