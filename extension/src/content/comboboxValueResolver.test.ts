import { describe, expect, it } from 'vitest';
import { resolveComboboxFillValueFromLabels } from './comboboxValueResolver';
import { createEmptyProfile } from '../profile/profileStore';

describe('resolveComboboxFillValueFromLabels', () => {
  it('prefers clearance screening answer over unrelated work authorization label bleed', () => {
    const profile = createEmptyProfile();
    profile.workAuthorization = 'Yes';

    const value = resolveComboboxFillValueFromLabels(
      [
        'U.S. WORK AUTHORIZATION',
        'CLEARANCE ELIGIBILITY - This position requires eligibility to obtain and maintain a U.S. security clearance.*'
      ],
      profile,
      'Anduril'
    );

    expect(value).toBe('No');
  });

  it('returns None for past clearance level question', () => {
    const profile = createEmptyProfile();

    const value = resolveComboboxFillValueFromLabels(
      ['If you have held a U.S. security clearance in the past, what clearance level have you held? *'],
      profile,
      'Anduril'
    );

    expect(value).toBe('N/A - have never held U.S. security clearance');
  });
});
