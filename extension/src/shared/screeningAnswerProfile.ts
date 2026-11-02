import { PROFILE_FORM_OPTIONS } from './applicationDefaults';
import {
  resolveEthnicGroupSelectValue,
  resolveGenderSelectValue,
  resolveRaceSelectValue
} from './eeoFillValues';
import { ScreeningAnswer, UserProfile } from './types';

export type ScreeningCategory =
  | 'authorization'
  | 'eligibility'
  | 'employer'
  | 'demographics'
  | 'compliance';

export const SCREENING_CATEGORY_LABELS: Record<ScreeningCategory, string> = {
  authorization: 'Work authorization & visa',
  eligibility: 'Eligibility & logistics',
  employer: 'Role & employer-specific',
  demographics: 'Demographics (linked to Self-ID below)',
  compliance: 'Background & compliance'
};

export const SCREENING_PROFILE_FIELD_LINKS: Partial<Record<string, keyof UserProfile>> = {
  'us-work-authorization': 'workAuthorization',
  'visa-sponsorship-needed': 'sponsorship',
  'gender-identity': 'gender',
  'transgender-identity': 'transgender',
  'racial-ethnic-background': 'raceEthnicity',
  'sexual-orientation': 'sexualOrientation'
};

export const PROFILE_TO_SCREENING_ID: Partial<Record<keyof UserProfile, string>> = {
  workAuthorization: 'us-work-authorization',
  sponsorship: 'visa-sponsorship-needed',
  gender: 'gender-identity',
  transgender: 'transgender-identity',
  raceEthnicity: 'racial-ethnic-background',
  sexualOrientation: 'sexual-orientation'
};

const SCREENING_CATEGORY_BY_ID: Record<string, ScreeningCategory> = {
  'us-work-authorization': 'authorization',
  'spouse-visa-status': 'authorization',
  'visa-sponsorship-needed': 'authorization',
  'legal-age-to-work': 'authorization',
  'at-least-18-years-old': 'authorization',
  'snap-eligibility-followup': 'authorization',
  'relocate-to-job-location': 'eligibility',
  'office-attendance-commitment': 'eligibility',
  'meets-minimum-experience': 'eligibility',
  'big-four-employment': 'eligibility',
  'government-employment': 'compliance',
  'background-check-willing': 'compliance',
  'bachelors-cs-engineering-experience': 'employer',
  'ms-minimum-qualifications-ack': 'employer',
  'ms-data-privacy-notice': 'employer',
  'ms-candidate-code-of-conduct': 'employer',
  'gender-identity': 'demographics',
  'transgender-identity': 'demographics',
  'racial-ethnic-background': 'demographics',
  'sexual-orientation': 'demographics'
};

export function getScreeningCategory(entry: ScreeningAnswer): ScreeningCategory {
  return SCREENING_CATEGORY_BY_ID[entry.id] || 'eligibility';
}

export function getScreeningAnswerOptions(entry: ScreeningAnswer, profile: UserProfile): string[] {
  switch (entry.id) {
    case 'gender-identity':
      return [...PROFILE_FORM_OPTIONS.gender];
    case 'transgender-identity':
      return [...PROFILE_FORM_OPTIONS.transgender];
    case 'racial-ethnic-background':
      return [...PROFILE_FORM_OPTIONS.raceEthnicity];
    case 'sexual-orientation':
      return [...PROFILE_FORM_OPTIONS.sexualOrientation];
    case 'us-work-authorization':
    case 'legal-age-to-work':
    case 'at-least-18-years-old':
    case 'background-check-willing':
    case 'relocate-to-job-location':
    case 'office-attendance-commitment':
    case 'meets-minimum-experience':
    case 'bachelors-cs-engineering-experience':
    case 'ms-minimum-qualifications-ack':
    case 'ms-data-privacy-notice':
    case 'ms-candidate-code-of-conduct':
      return ['Yes', 'No'];
    case 'visa-sponsorship-needed':
      return ['Yes', 'No'];
    case 'spouse-visa-status':
    case 'snap-eligibility-followup':
    case 'big-four-employment':
    case 'government-employment':
      return ['Yes', 'No'];
    default:
      if (entry.answer && !['Yes', 'No'].includes(entry.answer)) {
        return [entry.answer, 'Yes', 'No'];
      }
      return ['Yes', 'No'];
  }
}

export function getWorkdayEeoPreview(profile: UserProfile): { label: string; value: string }[] {
  return [
    { label: 'Indicate Gender', value: resolveGenderSelectValue(profile.gender) },
    { label: 'Indicate Ethnic group', value: resolveEthnicGroupSelectValue(profile.hispanic) },
    {
      label: 'Indicate your Race',
      value: resolveRaceSelectValue(profile.raceEthnicity, profile.hispanic)
    }
  ];
}

export const PROFILE_ADDRESS_FIELD_KEYS = new Set([
  'addressLine1',
  'street',
  'city',
  'state',
  'country',
  'zip',
  'postalCode'
]);
