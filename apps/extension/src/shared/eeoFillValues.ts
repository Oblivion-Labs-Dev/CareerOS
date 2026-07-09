import { APPLICATION_FIELD_DEFAULTS } from './applicationDefaults';
import { UserProfile } from './types';

/** Map profile gender to common ATS dropdown labels (Male/Man, Female/Woman). */
export function resolveGenderSelectValue(gender?: string): string {
  const value = gender?.trim() || '';
  if (/^man$/i.test(value)) return 'Male';
  if (/^woman$/i.test(value)) return 'Female';
  return value || APPLICATION_FIELD_DEFAULTS.gender;
}

/** Hispanic/Latino origin dropdowns (Workday "Indicate Ethnic group"). */
export function resolveEthnicGroupSelectValue(hispanic?: string): string {
  const value = hispanic?.trim() || '';
  if (/^no$/i.test(value) || /not hispanic/i.test(value)) return 'Not Hispanic or Latino';
  if (/^yes$/i.test(value) || /hispanic or latino/i.test(value)) return 'Hispanic or Latino';
  return value || APPLICATION_FIELD_DEFAULTS.hispanic;
}

/** Race dropdowns with Hispanic/Latino qualifier (Workday "Indicate your Race"). */
export function resolveRaceSelectValue(raceEthnicity?: string, hispanic?: string): string {
  const race = raceEthnicity?.trim() || '';
  const notHispanic = /^no$/i.test(hispanic?.trim() || '') || /not hispanic/i.test(hispanic || '');

  if (/south asian/i.test(race)) {
    return notHispanic ? 'Asian (Not Hispanic or Latino)' : race;
  }
  if (/^asian$/i.test(race) && notHispanic) {
    return 'Asian (Not Hispanic or Latino)';
  }
  if (/^white$/i.test(race) && notHispanic) {
    return 'White (Not Hispanic or Latino)';
  }
  if (/^black/i.test(race) && notHispanic) {
    return 'Black or African American (Not Hispanic or Latino)';
  }

  return race || APPLICATION_FIELD_DEFAULTS.raceEthnicity;
}

export function resolveVeteranSelectValue(veteran?: string): string {
  return veteran?.trim() || APPLICATION_FIELD_DEFAULTS.veteran;
}

export function resolveDisabilitySelectValue(disability?: string): string {
  return disability?.trim() || APPLICATION_FIELD_DEFAULTS.disability;
}

export function resolveEeoComboboxValue(label: string, profile: UserProfile): string | undefined {
  const normalized = label.replace(/\*+$/, '').replace(/\s+/g, ' ').trim();

  if (/indicate gender|^gender$/i.test(normalized) && !/identity|transgender|sexual/.test(normalized)) {
    return resolveGenderSelectValue(profile.gender);
  }
  if (/indicate ethnic|ethnic group|hispanic.*latino|latino.*origin/i.test(normalized) && !/race/.test(normalized)) {
    return resolveEthnicGroupSelectValue(profile.hispanic);
  }
  if (/indicate your race|^race$/i.test(normalized) || (/race/i.test(normalized) && !/ethnic group/.test(normalized))) {
    return resolveRaceSelectValue(profile.raceEthnicity, profile.hispanic);
  }
  if (/protected veteran|veteran status|categories of protected veterans/i.test(normalized)) {
    return resolveVeteranSelectValue(profile.veteran);
  }
  if (/disability|form cc-305|cc-305/i.test(normalized)) {
    return resolveDisabilitySelectValue(profile.disability);
  }

  return undefined;
}
