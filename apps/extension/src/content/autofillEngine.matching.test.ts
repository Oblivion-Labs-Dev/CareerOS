import { describe, expect, it } from 'vitest';
import { matchesCustomOption, isSynonymMatch, matchesRadioOption, scoreSelectOptionMatch, pickBestMatchingOptionText } from './autofillEngine.matching';
import { APPLICATION_FIELD_DEFAULTS } from '../shared/applicationDefaults';

describe('dropdown option matching', () => {
  it('maps prefer-not-to-answer profile values to Rippling disability option text', () => {
    expect(matchesCustomOption("I don't wish to answer", 'Prefer not to answer')).toBe(true);
    expect(isSynonymMatch("I don't wish to answer", 'Prefer not to answer')).toBe(true);
  });

  it('maps prefer-not-to-answer profile values to Rippling veteran option text', () => {
    expect(matchesCustomOption('Choose not to disclose', 'Prefer not to answer')).toBe(true);
  });

  it('does not map prefer-not-to-answer to unrelated no answers', () => {
    expect(matchesCustomOption("No, I don't have a disability", 'Prefer not to answer')).toBe(false);
    expect(matchesCustomOption('I am not a protected veteran', 'Prefer not to answer')).toBe(false);
  });

  it('still matches direct yes/no demographic answers', () => {
    expect(matchesCustomOption('No', 'No')).toBe(true);
    expect(matchesCustomOption('Male', 'Male')).toBe(true);
    expect(matchesCustomOption('Asian', 'Asian')).toBe(true);
  });

  it('matches Rippling veteran and disability default answers', () => {
    expect(matchesCustomOption('I am not a protected veteran', APPLICATION_FIELD_DEFAULTS.veteran)).toBe(true);
    expect(matchesCustomOption("No, I don't have a disability", APPLICATION_FIELD_DEFAULTS.disability)).toBe(true);
    expect(
      matchesCustomOption(
        'No, I do not have a disability and have not had one in the past.',
        APPLICATION_FIELD_DEFAULTS.disability
      )
    ).toBe(true);
  });

  it('picks the best dropdown option instead of partial text matches', () => {
    const options = ['Male', 'Female', 'Decline to Self Identify'];
    expect(pickBestMatchingOptionText(options, 'Man')).toBe('Male');
    expect(pickBestMatchingOptionText(['Not Hispanic or Latino', 'Hispanic or Latino'], 'No')).toBe(
      'Not Hispanic or Latino'
    );
    expect(
      pickBestMatchingOptionText(
        ['Asian (Not Hispanic or Latino)', 'White (Not Hispanic or Latino)'],
        'South Asian'
      )
    ).toBe('Asian (Not Hispanic or Latino)');
  });

  it('scores weak substring matches below selection threshold', () => {
    expect(scoreSelectOptionMatch('Male', 'Man')).toBeGreaterThanOrEqual(75);
    expect(scoreSelectOptionMatch('Management', 'Man')).toBeLessThan(75);
  });

  it('matches pronoun sets regardless of order or separators', () => {
    expect(matchesCustomOption('He/him/his', 'him his he')).toBe(true);
    expect(matchesCustomOption('him his he', 'He/him/his')).toBe(true);
    expect(matchesCustomOption('Just use my name', 'Prefer not to say')).toBe(true);
    expect(matchesCustomOption('He/him/his', 'Just use my name')).toBe(false);
  });

  it('matches SMS consent radio label', () => {
    expect(
      matchesRadioOption(
        'No - I do not consent to receiving text messages',
        APPLICATION_FIELD_DEFAULTS.smsConsent
      )
    ).toBe(true);
  });
});
