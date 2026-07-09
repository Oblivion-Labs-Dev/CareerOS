import { describe, expect, it } from 'vitest';
import {
  matchScreeningAnswer,
  appendScreeningAnswerForLabel,
  mergeDefaultScreeningAnswers,
  syncProfileFromScreeningAnswers
} from '../shared/screeningAnswers';
import { createEmptyProfile } from '../profile/profileStore';

describe('screeningAnswers', () => {
  it('matches Microsoft work authorization wording', () => {
    const profile = createEmptyProfile();
    profile.workAuthorization = 'Yes';

    const answer = matchScreeningAnswer(
      'Are you legally authorized to work in the country/region you are applying for?',
      profile
    );

    expect(answer).toBe('Yes');
  });

  it('matches Microsoft sponsorship wording', () => {
    const profile = createEmptyProfile();
    profile.sponsorship = 'No';

    const answer = matchScreeningAnswer(
      "In order to obtain or maintain employment eligibility, will you now or in the future require the company's sponsorship for an immigration-related employment benefit (i.e., a work visa, work permit, etc.)?",
      profile
    );

    expect(answer).toBe('No');
  });

  it('persists a new learned screening question', () => {
    const profile = createEmptyProfile();
    profile.workAuthorization = 'Yes';

    const updated = appendScreeningAnswerForLabel(
      profile,
      'Are you legally authorized to work in the country/region you are applying for?',
      'Yes',
      'workAuthorization'
    );

    expect(updated.screeningAnswers?.some((entry) => entry.question.includes('country/region'))).toBe(true);
  });

  it('matches Microsoft CS degree and engineering experience question', () => {
    const profile = createEmptyProfile();

    const answer = matchScreeningAnswer(
      "Do you have a Bachelor's Degree in Computer Science or related technical field AND 4+ years technical engineering experience with coding in languages including, but not limited to, C, C++, C#, Java, JavaScript, or Python ?",
      profile
    );

    expect(answer).toBe('Yes');
  });

  it('matches Microsoft acknowledgment checkboxes', () => {
    const profile = createEmptyProfile();

    expect(
      matchScreeningAnswer(
        'As part of the online application process you were asked whether you possess certain minimum required qualifications for the role to which you are applying. By selecting yes, you agree that you answered these questions accurately.',
        profile
      )
    ).toBe('Yes');
    expect(
      matchScreeningAnswer('By checking this you agree to the Microsoft Data Privacy Notice (DPN).', profile)
    ).toBe('Yes');
    expect(
      matchScreeningAnswer(
        'By checking this, you affirm that you have familiarized yourself with the Microsoft recruiting process and agree to the candidate code of conduct.',
        profile
      )
    ).toBe('Yes');
  });

  it('merges default screening answers and syncs profile fields', () => {
    const profile = createEmptyProfile();
    profile.gender = 'Man';
    profile.transgender = 'No';
    profile.raceEthnicity = 'South Asian';
    profile.sexualOrientation = 'Heterosexual';

    const synced = syncProfileFromScreeningAnswers(profile);
    const ids = new Set(synced.screeningAnswers?.map((entry) => entry.id));

    expect(ids.has('gender-identity')).toBe(true);
    expect(ids.has('ms-minimum-qualifications-ack')).toBe(true);
    expect(synced.screeningAnswers?.find((e) => e.id === 'gender-identity')?.answer).toBe('Man');
    expect(synced.screeningAnswers?.find((e) => e.id === 'transgender-identity')?.answer).toBe('No');
    expect(mergeDefaultScreeningAnswers([]).length).toBeGreaterThan(15);
  });
});
