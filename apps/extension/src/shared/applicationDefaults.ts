/** Default answers used when profile values are not set for common ATS fields. */
export const APPLICATION_FIELD_DEFAULTS = {
  gender: 'Prefer not to answer',
  raceEthnicity: 'Prefer not to answer',
  hispanic: 'Prefer not to answer',
  veteran: 'I am not a protected veteran',
  disability: "No, I don't have a disability",
  smsConsent: 'No - I do not consent to receiving text messages',
  pronouns: 'Prefer not to say'
} as const;

export type ApplicationDefaultKey = keyof typeof APPLICATION_FIELD_DEFAULTS;

/** Common dropdown options shown on the profile page (matches Workday / Greenhouse wording). */
export const PROFILE_FORM_OPTIONS = {
  gender: [
    'Male',
    'Female',
    'Non-binary',
    'Decline to Self Identify',
    APPLICATION_FIELD_DEFAULTS.gender
  ],
  raceEthnicity: [
    'Asian',
    'White',
    'Black or African American',
    'Hispanic or Latino',
    'American Indian or Alaska Native',
    'Native Hawaiian or Other Pacific Islander',
    'Two or More Races',
    APPLICATION_FIELD_DEFAULTS.raceEthnicity
  ],
  hispanic: ['No', 'Yes', APPLICATION_FIELD_DEFAULTS.hispanic],
  veteran: [
    APPLICATION_FIELD_DEFAULTS.veteran,
    'I identify as one or more of the classifications of protected veteran',
    'Prefer not to answer'
  ],
  disability: [
    APPLICATION_FIELD_DEFAULTS.disability,
    "Yes, I have a disability (or previously had a disability)",
    'Prefer not to answer'
  ],
  smsConsent: [
    APPLICATION_FIELD_DEFAULTS.smsConsent,
    'Yes - I consent to receiving text messages'
  ]
} as const;
