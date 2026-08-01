/** Common ATS dropdown options for profile screening fields. */
export const PROFILE_FORM_OPTIONS: Record<string, string[]> = {
  gender: [
    "Man",
    "Male",
    "Woman",
    "Female",
    "Non-binary",
    "Decline to Self Identify",
    "Prefer not to answer",
  ],
  transgender: ["No", "Yes", "Prefer not to answer"],
  sexualOrientation: [
    "Heterosexual",
    "Gay",
    "Lesbian",
    "Bisexual and/or pansexual",
    "Queer",
    "Asexual",
    "Prefer not to answer",
  ],
  raceEthnicity: [
    "South Asian",
    "Asian",
    "White",
    "Black or African American",
    "Hispanic or Latino",
    "American Indian or Alaska Native",
    "Native Hawaiian or Other Pacific Islander",
    "Two or More Races",
    "Prefer not to answer",
  ],
  hispanic: ["No", "Yes", "Prefer not to answer"],
  veteran: [
    "I am not a protected veteran",
    "I identify as one or more of the classifications of protected veteran",
    "Prefer not to answer",
  ],
  disability: [
    "No, I don't have a disability",
    "Yes, I have a disability (or previously had a disability)",
    "Prefer not to answer",
  ],
  workAuthorization: ["Yes", "No"],
  sponsorship: ["Yes", "No"],
  pronouns: ["He/Him", "She/Her", "They/Them", "Prefer not to say"],
};

export const PROFILE_KEY_LABELS: Record<string, string> = {
  gender: "Gender identity",
  transgender: "Transgender experience",
  sexualOrientation: "Sexual orientation",
  raceEthnicity: "Race / ethnicity",
  hispanic: "Hispanic / Latino",
  veteran: "Veteran status",
  disability: "Disability status",
  workAuthorization: "Work authorization",
  sponsorship: "Visa sponsorship",
  pronouns: "Pronouns",
  salaryExpectations: "Salary expectations",
};

const PHONE_COUNTRY_OPTION_RE = /^.+\s\+\d{1,4}$/;

export function looksLikePhoneCountryOptions(options: string[]): boolean {
  if (options.length < 5) return false;
  const matches = options.filter((opt) => PHONE_COUNTRY_OPTION_RE.test(opt.trim())).length;
  return matches >= Math.max(3, Math.floor(options.length * 0.6));
}

export function normalizeFieldOptions(options: string[] | undefined | null): string[] {
  const seen = new Set<string>();
  const cleaned: string[] = [];
  for (const raw of options || []) {
    const opt = raw.trim();
    if (!opt) continue;
    const lower = opt.toLowerCase();
    if (lower.startsWith("select") || lower.startsWith("choose") || lower.startsWith("please select")) continue;
    if (seen.has(lower)) continue;
    seen.add(lower);
    cleaned.push(opt);
  }
  return cleaned;
}

export function optionsForQuestion(field: {
  suggestedProfileKey?: string | null;
  options?: string[];
  fieldType?: string;
  label?: string;
  displayTitle?: string;
}): string[] {
  const fromApplication = normalizeFieldOptions(field.options);
  if (fromApplication.length > 0 && !looksLikePhoneCountryOptions(fromApplication)) {
    return fromApplication;
  }

  if (field.suggestedProfileKey && PROFILE_FORM_OPTIONS[field.suggestedProfileKey]) {
    return PROFILE_FORM_OPTIONS[field.suggestedProfileKey];
  }
  return [];
}

function questionText(field: { label?: string; displayTitle?: string }): string {
  return `${field.label || ""} ${field.displayTitle || ""}`.toLowerCase();
}

export function isConsentQuestion(field: {
  label?: string;
  displayTitle?: string;
  fieldType?: string;
}): boolean {
  const text = questionText(field);
  return (
    /^(checkbox|boolean)$/i.test(field.fieldType || "")
    || /privacy policy|i understand|i agree|consent|checking this box|candidate privacy/.test(text)
  );
}

export function isFreeTextApplicationQuestion(field: {
  label?: string;
  displayTitle?: string;
  fieldType?: string;
}): boolean {
  const text = questionText(field);
  return /cities|available to work|languages|speak fluently|fluent in/.test(text);
}

/** @deprecated Use optionsForQuestion — kept for callers that pass profile key + options separately */
export function optionsForProfileKey(profileKey: string | null | undefined, fieldOptions: string[]): string[] {
  return optionsForQuestion({ suggestedProfileKey: profileKey, options: fieldOptions });
}
