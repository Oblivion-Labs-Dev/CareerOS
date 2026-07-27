import { ScannedField, getComboboxLabelCandidates } from './domScanner';
import { resolveComboboxFillValueFromLabels } from './comboboxValueResolver';
import { UserProfile } from '../shared/types';
import { APPLICATION_FIELD_DEFAULTS, ApplicationDefaultKey } from '../shared/applicationDefaults';
import { resolvePronounFillValue } from './autofillEngine.matching';
import { enrichProfile } from '../profile/profileStore';
import { matchQuestion } from '../learning/learningEngine';
import { stringSimilarity } from '../learning/fuzzyMatcher';
import { inferRemainingValue, resolveFieldLabel, hasRipplingContactDataInput, RIPPLING_DATA_INPUT_TO_CANONICAL, getRipplingDataInput, isPhoneCountryLabel, resolvePhoneCountryFillValue, isScreeningQuestionLabel } from './fieldInference';
import { resolveMostRecentEmployer } from '../shared/workExperience';
import { addressValueForKey } from '../profile/addressProfile';
import { matchScreeningAnswer } from '../shared/screeningAnswers';
import { isOptionalAddressField } from './fieldRequired';
import { lookupFieldMapping } from '../learning/fieldMappingMemory';
import { detectUploadKindFromHint } from './fileUploadDetection';

export interface ClassifiedField {
  id: string;
  scannedField: ScannedField;
  canonicalKey?: string;
  proposedValue?: string;
  confidence: 'high' | 'medium' | 'low';
  reason: string;
  learnedId?: string; // If matched from memory
}

const CANONICAL_PATTERNS: Record<string, RegExp[]> = {
  firstName: [/first[\s_-]*name/i, /^fname$/i, /given[\s_-]*name/i, /^given-name$/i],
  lastName: [/last[\s_-]*name/i, /^lname$/i, /family[\s_-]*name/i, /surname/i, /^family-name$/i],
  fullName: [/full\s*name/i, /^name/i, /applicant\s*name/i, /legal\s*name/i],
  preferredName: [/preferred\s*name/i, /name\s*you\s*go\s*by/i, /what.*call\s*you/i],
  email: [/email/i, /e-mail/i],
  phone: [/phone/i, /telephone/i, /mobile/i, /tel\b/i],
  location: [
    /location/i,
    /city.*state/i,
    /where.*(live|located)/i,
    /residence/i,
    /work location/i
  ],
  currentCompany: [
    /current\s*company/i,
    /present\s*employer/i,
    /company\s*name/i,
    /most\s+recently\s+worked/i,
    /where.*most\s+recently\s+worked/i,
    /recent\s+employer/i,
    /last\s+(?:company|employer)/i,
    /where.*you.*worked/i
  ],
  address: [/address/i, /street/i],
  city: [/city/i],
  state: [/state/i, /province/i],
  zip: [/zip/i, /postal\s*code/i, /postal/i, /postcode/i],
  country: [/country/i],
  linkedin: [/linkedin/i],
  github: [/github/i],
  portfolio: [/portfolio/i, /website/i, /personal\s*site/i],
  resume: [/resume/i, /\bcv\b/i, /curriculum\s*vitae/i],
  coverLetter: [/cover\s*letter/i, /writing\s*sample/i],
  workAuthorization: [/authorized/i, /right\s*to\s*work/i, /permit/i, /eligible\s*to\s*work/i, /legally\s*work/i, /work\s*status/i],
  sponsorship: [/sponsor/i, /visa\s*sponsorship/i, /require\s*sponsorship/i, /need\s*sponsorship/i, /immigration/i, /\bh-?1b\b/i],
  gender: [/gender/i, /sex\b/i],
  pronouns: [/pronoun/i],
  veteran: [/veteran/i],
  disability: [/disability/i],
  raceEthnicity: [/please identify your race/i, /\brace\b/i, /ethnicity/i],
  hispanic: [/hispanic/i, /latino/i],
  smsConsent: [/text\s*message/i, /\bsms\b/i, /consent.*(text|message)/i],
  salary: [/salary/i, /compensation/i, /expectations/i],
  noticePeriod: [/notice/i, /start\s*date/i, /availability/i],
  yearsExperience: [/years\s*of\s*experience/i, /experience\s*level/i]
};

const SELECT_CONTACT_KEYS = new Set([
  'phone',
  'email',
  'location',
  'linkedin',
  'github',
  'portfolio',
  'firstName',
  'lastName',
  'fullName',
  'currentCompany'
]);

function profileValueForField(
  field: ScannedField,
  matchedKey: string,
  profile: UserProfile
): string {
  if (matchedKey === 'state' || matchedKey === 'city' || matchedKey === 'zip' || matchedKey === 'address') {
    return addressValueForKey(matchedKey, profile);
  }
  if (matchedKey === 'country') {
    if (isPhoneCountryLabel(field.labelText)) {
      return resolvePhoneCountryFillValue(profile);
    }
    return addressValueForKey('country', profile);
  }

  if (
    field.type === 'select' &&
    SELECT_CONTACT_KEYS.has(matchedKey) &&
    !hasRipplingContactDataInput(field)
  ) {
    return '';
  }
  if (matchedKey === 'pronouns') {
    return resolvePronounFillValue(profile.pronouns);
  }
  if (matchedKey === 'currentCompany') {
    return resolveMostRecentEmployer(profile);
  }
  const val = profile[matchedKey as keyof UserProfile];
  return typeof val === 'string' ? val.trim() : '';
}

function detectUploadCanonicalKey(field: ScannedField): 'resume' | 'coverLetter' | null {
  const hint = `${field.labelText} ${field.placeholder} ${field.name}`.toLowerCase();
  return detectUploadKindFromHint(hint);
}

/**
 * Classifies a set of scanned fields using rule-based patterns and the learned answer engine.
 */
export async function classifyFields(
  fields: ScannedField[],
  profile: UserProfile,
  company?: string,
  domain?: string
): Promise<ClassifiedField[]> {
  const enrichedProfile = enrichProfile(profile);
  const result: ClassifiedField[] = [];

  for (const field of fields) {
    const uploadKey = detectUploadCanonicalKey(field);
    if (uploadKey) {
      result.push({
        id: field.id,
        scannedField: field,
        canonicalKey: uploadKey,
        proposedValue: uploadKey === 'coverLetter' ? '[Cover Letter Default]' : '[Resume Default]',
        confidence: 'high',
        reason: 'Detected file upload zone'
      });
      continue;
    }

    const ripplingInput = getRipplingDataInput(field.element);
    if (ripplingInput && ripplingInput in RIPPLING_DATA_INPUT_TO_CANONICAL) {
      const canonical = RIPPLING_DATA_INPUT_TO_CANONICAL[ripplingInput];
      const proposed = profileValueForField(field, canonical, enrichedProfile);
      if (proposed) {
        result.push({
          id: field.id,
          scannedField: field,
          canonicalKey: canonical,
          proposedValue: proposed,
          confidence: 'high',
          reason: `Rippling data-input="${ripplingInput}"`
        });
        continue;
      }
    }

    const autocomplete = (field.autocomplete || '').toLowerCase();
    const autocompleteKey =
      autocomplete === 'given-name' || autocomplete === 'fname'
        ? 'firstName'
        : autocomplete === 'family-name' || autocomplete === 'lname'
          ? 'lastName'
          : autocomplete === 'name'
            ? 'fullName'
            : undefined;
    if (autocompleteKey) {
      const proposed = profileValueForField(field, autocompleteKey, enrichedProfile);
      if (proposed) {
        result.push({
          id: field.id,
          scannedField: field,
          canonicalKey: autocompleteKey,
          proposedValue: proposed,
          confidence: 'high',
          reason: `Autocomplete="${autocomplete}"`
        });
        continue;
      }
    }

    const resolvedLabel = resolveFieldLabel(field);
    const savedMapping = await lookupFieldMapping(domain, resolvedLabel || field.labelText, field.type);
    if (savedMapping) {
      result.push({
        id: field.id,
        scannedField: field,
        canonicalKey: savedMapping.canonicalKey,
        proposedValue: savedMapping.value,
        confidence: savedMapping.confidence >= 0.85 ? 'high' : savedMapping.confidence >= 0.6 ? 'medium' : 'low',
        reason: 'Saved ATS field mapping',
      });
      continue;
    }

    const clues = [
      { text: resolvedLabel, weight: 3, label: 'Label' },
      { text: field.labelText, weight: 2.5, label: 'Direct label' },
      { text: field.placeholder, weight: 2, label: 'Placeholder' },
      { text: field.name, weight: 1.5, label: 'Name attribute' },
      { text: field.htmlId, weight: 1.5, label: 'ID attribute' },
      { text: field.autocomplete, weight: 1, label: 'Autocomplete' }
    ];

    let matchedKey: string | undefined;
    let maxWeight = 0;
    let matchReason = '';

    // 1. Try pattern rules first
    for (const [key, patterns] of Object.entries(CANONICAL_PATTERNS)) {
      if (key === 'resume' || key === 'coverLetter') {
        if (field.type !== 'file') continue;
      } else {
        if (field.type === 'file') continue;
      }

      for (const pattern of patterns) {
        for (const clue of clues) {
          if (!clue.text) continue;
          if (key === 'address' && isOptionalAddressField(clue.text)) continue;
          if (
            ['state', 'city', 'zip', 'country', 'location'].includes(key) &&
            isScreeningQuestionLabel(clue.text)
          ) {
            continue;
          }
          if (pattern.test(clue.text)) {
            if (clue.weight > maxWeight) {
              maxWeight = clue.weight;
              matchedKey = key;
              matchReason = `Rule matched ${clue.label} against pattern`;
            }
          }
        }
      }
    }

    // Propose value from profile if matched
    let proposedValue = '';
    let confidence: 'high' | 'medium' | 'low' = 'low';

    if (matchedKey) {
      if (matchedKey in enrichedProfile) {
        proposedValue = profileValueForField(field, matchedKey, enrichedProfile);
        if (proposedValue) {
          confidence = maxWeight >= 2.5 ? 'high' : 'medium';
        } else {
          confidence = 'low';
        }
      } else if (matchedKey === 'resume') {
        proposedValue = '[Resume Default]';
        confidence = 'high';
      } else if (matchedKey === 'coverLetter') {
        proposedValue = '[Cover Letter Default]';
        confidence = 'high';
      } else if (matchedKey === 'currentCompany') {
        proposedValue = profileValueForField(field, matchedKey, enrichedProfile);
        if (!proposedValue) {
          proposedValue = enrichedProfile.currentTitle || '';
        }
        if (proposedValue) {
          confidence = 'medium';
          matchReason = enrichedProfile.currentCompany
            ? 'Mapped from profile current company'
            : 'Mapped current company from profile current title';
        }
      }
    }

    if (!proposedValue && enrichedProfile.customFields) {
      const label = field.labelText || field.name || field.placeholder || '';
      if (label) {
        for (const [customLabel, customVal] of Object.entries(enrichedProfile.customFields)) {
          if (stringSimilarity(label.toLowerCase(), customLabel.toLowerCase()) > 0.75) {
            proposedValue = customVal;
            confidence = 'high';
            matchedKey = matchedKey || 'customQuestion';
            matchReason = `Matched custom profile field "${customLabel}"`;
            break;
          }
        }
      }
    }

    if (!proposedValue && field.type === 'select') {
      const labelCandidates = getComboboxLabelCandidates(field.element, document);
      const fromCombobox = resolveComboboxFillValueFromLabels(labelCandidates, enrichedProfile, company);
      if (fromCombobox) {
        proposedValue = fromCombobox;
        confidence = 'high';
        matchedKey = matchedKey || 'screeningAnswer';
        matchReason = 'Matched combobox label to profile screening/default answer';
      }
    }

    if (!proposedValue) {
      const questionText = resolveFieldLabel(field) || field.labelText || field.name;
      if (isScreeningQuestionLabel(questionText)) {
        const screeningAnswer = matchScreeningAnswer(questionText, enrichedProfile, company);
        if (screeningAnswer) {
          proposedValue = screeningAnswer;
          confidence = 'high';
          matchedKey = matchedKey || 'screeningAnswer';
          matchReason = 'Matched profile screening answer';
        }
      }
    }

    // 2. Query learned answers when we still do not have a value to fill
    if (!proposedValue) {
      const questionText = resolveFieldLabel(field) || field.labelText || field.name;
      const match = await matchQuestion(
        questionText,
        field.type,
        field.options,
        company,
        domain
      );

      if (match && match.score > (matchedKey ? 0.6 : 0.45)) {
        confidence = match.confidence;
        proposedValue = match.learnedAnswer.answer;
        matchedKey = match.learnedAnswer.canonicalKey || matchedKey || 'customQuestion';
        matchReason = `Memory match (${Math.round(match.score * 100)}% similarity)`;
      }
    }

    // 3. Apply defaults for demographic and consent fields when still empty
    if (matchedKey && !proposedValue && matchedKey in APPLICATION_FIELD_DEFAULTS) {
      const fromProfile = profileValueForField(field, matchedKey, enrichedProfile);
      proposedValue = fromProfile || APPLICATION_FIELD_DEFAULTS[matchedKey as ApplicationDefaultKey];
      confidence = fromProfile ? 'high' : 'medium';
      matchReason = fromProfile ? 'Profile answer' : 'Application default answer';
    }

    // 4. Final inference pass — leave no fillable field empty
    if (!proposedValue) {
      const inferred = inferRemainingValue(field, enrichedProfile, matchedKey, company);
      if (inferred.value) {
        proposedValue = inferred.value;
        confidence = confidence === 'low' ? 'medium' : confidence;
        matchedKey = matchedKey || inferred.canonicalKey || 'customQuestion';
        matchReason = inferred.reason;
      }
    }

    result.push({
      id: field.id,
      scannedField: field,
      canonicalKey: matchedKey,
      proposedValue,
      confidence,
      reason: matchReason || 'No match found'
    });
  }

  return result;
}
