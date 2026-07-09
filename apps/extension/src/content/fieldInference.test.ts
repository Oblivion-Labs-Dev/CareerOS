import { describe, expect, it } from 'vitest';
import { isScreeningQuestionLabel } from './fieldInference';

describe('isScreeningQuestionLabel', () => {
  it('detects government employment screening questions', () => {
    expect(
      isScreeningQuestionLabel(
        'Are you currently or have you ever been a member of the military, a civilian employee, or an official of any government, whether national, state, local, or foreign?'
      )
    ).toBe(true);
  });

  it('does not treat address state fields as screening questions', () => {
    expect(isScreeningQuestionLabel('State *')).toBe(false);
    expect(isScreeningQuestionLabel('State/Province')).toBe(false);
  });
});
