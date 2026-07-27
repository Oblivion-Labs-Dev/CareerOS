import { describe, expect, it } from 'vitest';
import {
  resolveDisabilitySelectValue,
  resolveEeoComboboxValue,
  resolveEthnicGroupSelectValue,
  resolveGenderSelectValue,
  resolveRaceSelectValue
} from './eeoFillValues';
import { UserProfile } from './types';

const baseProfile: UserProfile = {
  firstName: 'Akshay',
  lastName: 'Borse',
  fullName: 'Akshay Borse',
  email: 'test@example.com',
  phone: '(425) 336-9852',
  location: 'Seattle, WA',
  linkedin: '',
  github: '',
  portfolio: '',
  workAuthorization: 'Yes',
  sponsorship: 'Yes',
  yearsExperience: '7',
  currentTitle: 'Engineer',
  targetRole: 'Engineer',
  salaryExpectations: '',
  gender: 'Man',
  hispanic: 'No',
  raceEthnicity: 'South Asian',
  veteran: 'I am not a protected veteran',
  disability: "No, I don't have a disability"
};

describe('eeoFillValues', () => {
  it('maps Man to Male for gender dropdowns', () => {
    expect(resolveGenderSelectValue('Man')).toBe('Male');
  });

  it('maps Hispanic No to Not Hispanic or Latino', () => {
    expect(resolveEthnicGroupSelectValue('No')).toBe('Not Hispanic or Latino');
  });

  it('maps South Asian to Workday race option', () => {
    expect(resolveRaceSelectValue('South Asian', 'No')).toBe('Asian (Not Hispanic or Latino)');
  });

  it('resolves Workday EEO labels from profile', () => {
    expect(resolveEeoComboboxValue('Indicate Gender:*', baseProfile)).toBe('Male');
    expect(resolveEeoComboboxValue('Indicate Ethnic group:*', baseProfile)).toBe('Not Hispanic or Latino');
    expect(resolveEeoComboboxValue('Indicate your Race:*', baseProfile)).toBe('Asian (Not Hispanic or Latino)');
    expect(resolveEeoComboboxValue('If you believe you belong to any of the categories of protected Veterans...', baseProfile)).toBe(
      'I am not a protected veteran'
    );
    expect(resolveEeoComboboxValue('Please review Form CC-305 at the link above before checking one of the boxes below.*', baseProfile)).toBe(
      "No, I don't have a disability"
    );
  });

  it('resolves simple EEO status labels', () => {
    expect(resolveEeoComboboxValue('Gender', baseProfile)).toBe('Male');
    expect(resolveEeoComboboxValue('Race', baseProfile)).toBe('Asian (Not Hispanic or Latino)');
    expect(resolveEeoComboboxValue('Veteran Status', baseProfile)).toBe('I am not a protected veteran');
    expect(resolveEeoComboboxValue('Disability Status (Click here for more information)', baseProfile)).toBe(
      "No, I don't have a disability"
    );
  });

  it('matches CC-305 disability option text', () => {
    expect(resolveDisabilitySelectValue("No, I don't have a disability")).toBe("No, I don't have a disability");
  });
});
