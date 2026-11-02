import { UserProfile } from '../shared/types';
import { APPLICATION_FIELD_DEFAULTS } from '../shared/applicationDefaults';
import {
  resolveDisabilitySelectValue,
  resolveEeoComboboxValue,
  resolveEthnicGroupSelectValue,
  resolveGenderSelectValue,
  resolveRaceSelectValue,
  resolveVeteranSelectValue
} from '../shared/eeoFillValues';
import { matchScreeningAnswer } from '../shared/screeningAnswers';
import { isScreeningQuestionLabel } from './fieldInference';
import { resolvePronounFillValue } from './autofillEngine.matching';
import { isPhoneCountryLabel, resolvePhoneCountryFillValue } from './fieldInference';
import { addressValueForKey } from '../profile/addressProfile';

const COMBOBOX_LABEL_RESOLVERS: {
  test: (label: string) => boolean;
  value: (profile: UserProfile) => string;
}[] = [
  { test: (l) => /pronoun/i.test(l), value: (p) => resolvePronounFillValue(p.pronouns) },
  {
    test: (l) => /indicate gender|^gender\s*\*?$/i.test(l.trim()) && !/identity|transgender|sexual/.test(l),
    value: (p) => resolveGenderSelectValue(p.gender)
  },
  {
    test: (l) => /\bgender\b/i.test(l) && !/identity|transgender|sexual/.test(l),
    value: (p) => resolveGenderSelectValue(p.gender)
  },
  {
    test: (l) => /transgender/i.test(l),
    value: (p) => p.transgender || APPLICATION_FIELD_DEFAULTS.transgender
  },
  {
    test: (l) => /indicate ethnic|ethnic group|hispanic.*latino/i.test(l) && !/race/.test(l),
    value: (p) => resolveEthnicGroupSelectValue(p.hispanic)
  },
  {
    test: (l) =>
      /indicate your race|^race\s*\*?$/i.test(l.trim()) ||
      (/race|ethnicity/i.test(l) && !/ethnic group|hispanic/.test(l)),
    value: (p) => resolveRaceSelectValue(p.raceEthnicity, p.hispanic)
  },
  {
    test: (l) => /race|ethnicity/i.test(l),
    value: (p) => resolveRaceSelectValue(p.raceEthnicity, p.hispanic)
  },
  { test: (l) => /hispanic|latino/i.test(l), value: (p) => resolveEthnicGroupSelectValue(p.hispanic) },
  {
    test: (l) => /protected veteran|veteran status|categories of protected veterans/i.test(l),
    value: (p) => resolveVeteranSelectValue(p.veteran)
  },
  { test: (l) => /veteran/i.test(l), value: (p) => resolveVeteranSelectValue(p.veteran) },
  {
    test: (l) => /disability|form cc-305|cc-305/i.test(l),
    value: (p) => resolveDisabilitySelectValue(p.disability)
  },
  {
    test: (l) =>
      /^country\s*\*?$/i.test(l.trim()) ||
      /region of residence|country\/region|mailing country|address.*country/i.test(l),
    value: (p) => addressValueForKey('country', p)
  },
  {
    test: (l) => isPhoneCountryLabel(l),
    value: (p) => resolvePhoneCountryFillValue(p)
  },
  {
    test: (l) => /\bstate\b|province/i.test(l),
    value: (p) => addressValueForKey('state', p)
  },
  {
    test: (l) => /\bcity\b/i.test(l),
    value: (p) => addressValueForKey('city', p)
  },
  {
    test: (l) =>
      /legally authorized|authorized to work|right to work|work authorization|u\.s\. work authorization/i.test(l) &&
      !/clearance|export control|protected individual|1324b/i.test(l),
    value: (p) => p.workAuthorization || 'Yes'
  },
  {
    test: (l) =>
      /sponsor|visa|immigration-related employment benefit|require.*sponsorship|h1b|h-1b/i.test(l),
    value: (p) => p.sponsorship || 'No'
  }
];

export function resolveComboboxFillValue(
  label: string,
  profile: UserProfile,
  company?: string
): string | undefined {
  const eeoValue = resolveEeoComboboxValue(label, profile)?.trim();
  if (eeoValue) return eeoValue;

  const fromScreening = matchScreeningAnswer(label, profile, company);
  if (fromScreening?.trim()) return fromScreening.trim();

  const resolver = COMBOBOX_LABEL_RESOLVERS.find((entry) => entry.test(label));
  const fromResolver = resolver?.value(profile)?.trim();
  if (fromResolver) return fromResolver;

  return undefined;
}

export function resolveComboboxFillValueFromLabels(
  labels: string[],
  profile: UserProfile,
  company?: string
): string | undefined {
  let bestScreening: { value: string; score: number } | undefined;

  for (const label of labels) {
    const trimmed = label.replace(/\*+$/, '').replace(/\s+/g, ' ').trim();
    if (!trimmed) continue;
    const screening = matchScreeningAnswer(label, profile, company)?.trim();
    if (!screening) continue;
    const score =
      (isScreeningQuestionLabel(trimmed) ? 1_000 : 0) +
      trimmed.length +
      (trimmed.includes('?') ? 50 : 0);
    if (!bestScreening || score > bestScreening.score) {
      bestScreening = { value: screening, score };
    }
  }
  if (bestScreening) return bestScreening.value;

  for (const label of labels) {
    const value = resolveComboboxFillValue(label, profile, company);
    if (value) return value;
  }
  return undefined;
}
