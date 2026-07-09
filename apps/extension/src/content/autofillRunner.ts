import { scanPage, ScannedField, getLabelText, getFieldGroupQuestion } from './domScanner';
import { classifyFields, ClassifiedField } from './fieldClassifier';
import { autofillFieldPriority, resolveFreshField } from './fieldResolver';
import {
  fillTextOrTextArea,
  fillSelect,
  fillRadio,
  fillCheckbox,
  fillFileInput,
  findNearbyFileInput,
  highlightField,
  fillCustomRadios
} from './autofillEngine';
import { UserProfile } from '../shared/types';
import { enrichProfile } from '../profile/profileStore';
import {
  inferRemainingValue,
  RIPPLING_DATA_INPUT_MAP,
  RIPPLING_DATA_INPUT_TO_CANONICAL,
  isPhoneCountryLabel,
  resolvePhoneCountryFillValue
} from './fieldInference';
import { resolvePronounFillValue } from './autofillEngine.matching';
import { APPLICATION_FIELD_DEFAULTS } from '../shared/applicationDefaults';
import {
  resolveDisabilitySelectValue,
  resolveEeoComboboxValue,
  resolveEthnicGroupSelectValue,
  resolveGenderSelectValue,
  resolveRaceSelectValue,
  resolveVeteranSelectValue
} from '../shared/eeoFillValues';
import { logToServer } from '../shared/serverLog';
import { traceStep } from '../shared/actionTrace';
import {
  collectClassificationDiagnostics,
  collectStillEmptyDiagnostics,
  FieldDiagnostic,
  logFieldDiagnostics
} from './autofillDiagnostics';
import { fillWorkExperienceSections } from './workExperienceAutofill';
import { stampFieldMarker } from './fieldMarker';
import { matchScreeningAnswer } from '../shared/screeningAnswers';
import { persistSkippedFieldValues } from './skippedFieldProfile';
import { hasFieldDisplayValue } from './fieldValue';
import { shouldAutofillField, isOptionalAddressField } from './fieldRequired';
import { addressValueForKey, captureAddressFromPage } from '../profile/addressProfile';

const RESUME_MARKER = '[Resume Default]';
const COVER_MARKER = '[Cover Letter Default]';

function resolveSelectElement(element: HTMLElement): HTMLElement {
  if (
    element instanceof HTMLInputElement &&
    element.getAttribute('data-input') === 'select-search-input'
  ) {
    const parent = element.closest('[role="combobox"]') as HTMLElement | null;
    if (parent) return parent;
  }
  return element;
}

const EEO_CANONICAL_KEYS = new Set([
  'pronouns',
  'gender',
  'transgender',
  'sexualOrientation',
  'raceEthnicity',
  'hispanic',
  'veteran',
  'disability'
]);

const SELECT_INFER_RE =
  /pronoun|gender|race|hispanic|veteran|disability|location|state|city|address|zip|postal|country|screening|Profile screening answer|Rippling data-input|Application default|Default radio|Inferred from label/i;

const RESUME_PARSE_WAIT_MS = 2500;

function isResumeAttached(doc: Document): boolean {
  const fileInputs = Array.from(doc.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
  return fileInputs.some((input) => (input.files?.length ?? 0) > 0);
}

async function attachResumeIfNeeded(profile: UserProfile, doc: Document): Promise<boolean> {
  if (!profile.resume || isResumeAttached(doc)) return false;

  const fileInputs = Array.from(doc.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
  const resumeInput =
    fileInputs.find((input) => {
      const hint = `${input.id} ${input.name} ${getLabelText(input, doc)}`.toLowerCase();
      return /résumé|resume|\bcv\b/.test(hint);
    }) ?? fileInputs[0];

  if (resumeInput) {
    fillFileInput(resumeInput, profile.resume);
    return true;
  }

  const dropZones = Array.from(doc.querySelectorAll('div, section, label, button, span')) as HTMLElement[];
  for (const zone of dropZones) {
    const text = zone.textContent?.replace(/\s+/g, ' ').trim() || '';
    if (!/drop or select/i.test(text)) continue;
    const nearby = findNearbyFileInput(zone, doc);
    if (nearby) {
      fillFileInput(nearby, profile.resume);
      return true;
    }
  }

  return false;
}

async function fillRipplingDataInputFields(profile: UserProfile, doc: Document): Promise<number> {
  let filled = 0;

  for (const [dataInput, resolver] of Object.entries(RIPPLING_DATA_INPUT_MAP)) {
    const value = resolver(profile)?.trim();
    if (!value) continue;

    const input = doc.querySelector(
      `[data-input="${dataInput}"]:not([type="hidden"]):not([type="file"])`
    ) as HTMLElement | null;
    if (!input) continue;

    const combobox =
      input.getAttribute('role') === 'combobox'
        ? input
        : (input.closest('[role="combobox"]') as HTMLElement | null);
    const displayText = combobox?.textContent?.replace(/\s+/g, ' ').trim() || '';
    if (combobox && displayText && !/^(search|select\.\.\.|select|textbox)$/i.test(displayText)) {
      continue;
    }
    if (!combobox && input instanceof HTMLInputElement && input.value?.trim()) continue;

    if (combobox || dataInput === 'pronouns') {
      const didFill = await fillSelect(combobox || input, value);
      if (didFill) filled++;
      await new Promise((r) => setTimeout(r, 150));
      continue;
    }

    if (input instanceof HTMLInputElement && fillTextOrTextArea(input, value)) {
      filled++;
      await new Promise((r) => setTimeout(r, 80));
    }
  }

  return filled;
}

const COMBOBOX_LABEL_RESOLVERS: {
  test: (label: string) => boolean;
  value: (profile: UserProfile) => string;
}[] = [
  { test: (l) => /pronoun/i.test(l), value: (p) => resolvePronounFillValue(p.pronouns) },
  {
    test: (l) => /indicate gender|^gender\s*\*?$/i.test(l.trim()) && !/identity|transgender|sexual/.test(l),
    value: (p) => resolveGenderSelectValue(p.gender)
  },
  { test: (l) => /\bgender\b/i.test(l) && !/identity|transgender|sexual/.test(l), value: (p) => resolveGenderSelectValue(p.gender) },
  {
    test: (l) => /transgender/i.test(l),
    value: (p) => p.transgender || APPLICATION_FIELD_DEFAULTS.transgender
  },
  {
    test: (l) => /indicate ethnic|ethnic group|hispanic.*latino/i.test(l) && !/race/.test(l),
    value: (p) => resolveEthnicGroupSelectValue(p.hispanic)
  },
  {
    test: (l) => /indicate your race|^race\s*\*?$/i.test(l.trim()) || (/race|ethnicity/i.test(l) && !/ethnic group|hispanic/.test(l)),
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
    test: (l) => isPhoneCountryLabel(l),
    value: (p) => resolvePhoneCountryFillValue(p)
  },
  {
    test: (l) => /region of residence|country\/region|mailing country|address.*country/.test(l),
    value: (p) => addressValueForKey('country', p)
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
    test: (l) => /legally authorized|authorized to work|right to work|work authorization/i.test(l),
    value: (p) => p.workAuthorization || 'Yes'
  },
  {
    test: (l) =>
      /sponsor|visa|immigration-related employment benefit|require.*sponsorship/i.test(l),
    value: (p) => p.sponsorship || 'No'
  }
];

function getComboboxDisplay(el: HTMLElement): string {
  if (el instanceof HTMLInputElement) {
    const val = el.value?.trim();
    if (val && !/^(search|select\.\.\.|select|textbox)$/i.test(val)) return val;
  }

  const root = (el.closest('[role="combobox"]') as HTMLElement | null) || el;
  const selectedChild = root.querySelector('p, span[class*="value"], [class*="singleValue"]');
  const childText = selectedChild?.textContent?.replace(/\s+/g, ' ').trim() || '';
  if (childText && !/^(select\.\.\.|select|search|textbox)$/i.test(childText)) return childText;

  const display = root.textContent?.replace(/\s+/g, ' ').trim() || '';
  return display;
}

function isComboboxUnfilled(el: HTMLElement): boolean {
  const display = getComboboxDisplay(el);
  return !display || /^(select\.\.\.|select|search|textbox)$/i.test(display);
}

/** Fill Rippling/custom comboboxes by walking fresh DOM labels (survives resume re-render). */
async function fillLabeledComboboxes(profile: UserProfile, doc: Document): Promise<number> {
  const enriched = enrichProfile(profile);
  let filled = 0;
  const filledRoots = new Set<HTMLElement>();

  for (const combobox of Array.from(doc.querySelectorAll('[role="combobox"]')) as HTMLElement[]) {
    const root = (combobox.closest('[role="combobox"]') as HTMLElement | null) || combobox;
    if (filledRoots.has(root)) continue;
    if (!isComboboxUnfilled(root)) continue;

    const label = getLabelText(root, doc);
    if (!label) continue;

    const eeoValue = resolveEeoComboboxValue(label, enriched)?.trim();
    const resolver = COMBOBOX_LABEL_RESOLVERS.find((entry) => entry.test(label));
    const value = (eeoValue || resolver?.value(enriched))?.trim();
    if (!value) continue;

    const didFill = await fillSelect(resolveSelectElement(root), value);
    if (didFill) {
      filledRoots.add(root);
      filled++;
    }
    await new Promise((r) => setTimeout(r, 300));
  }

  return filled;
}

async function fillLabeledRadioGroups(
  profile: UserProfile,
  doc: Document,
  company?: string
): Promise<number> {
  const enriched = enrichProfile(profile);
  let filled = 0;
  const processedNames = new Set<string>();

  for (const radio of Array.from(doc.querySelectorAll('input[type="radio"]')) as HTMLInputElement[]) {
    const name = radio.name;
    if (!name || processedNames.has(name)) continue;
    processedNames.add(name);

    const group = Array.from(
      doc.querySelectorAll<HTMLInputElement>(`input[type="radio"][name="${CSS.escape(name)}"]`)
    );
    if (group.some((option) => option.checked)) continue;

    const question = getFieldGroupQuestion(radio, doc);
    if (!question) continue;

    const answer = matchScreeningAnswer(question, enriched, company);
    if (!answer) continue;

    fillRadio(radio, answer, doc);
    if (group.some((option) => option.checked)) {
      filled++;
    }
  }

  return filled;
}

function resolveAcknowledgmentAnswer(question: string, profile: UserProfile, company?: string): string | undefined {
  const fromScreening = matchScreeningAnswer(question, profile, company);
  if (fromScreening) return fromScreening;

  const normalized = question.replace(/\s+/g, ' ').trim().toLowerCase();
  if (
    /minimum required qualifications|answered these questions accurately|acknowledg.*minimum/.test(normalized)
  ) {
    return 'Yes';
  }
  if (/data privacy notice|microsoft data privacy|\bdpn\b/.test(normalized)) {
    return 'Yes';
  }
  if (/candidate code of conduct|microsoft recruiting process|familiarized yourself with the microsoft recruiting/.test(normalized)) {
    return 'Yes';
  }

  return undefined;
}

async function fillAcknowledgmentCheckboxes(
  profile: UserProfile,
  doc: Document,
  company?: string
): Promise<number> {
  const enriched = enrichProfile(profile);
  let filled = 0;

  for (const checkbox of Array.from(doc.querySelectorAll('input[type="checkbox"]')) as HTMLInputElement[]) {
    if (checkbox.checked) continue;

    const question = getFieldGroupQuestion(checkbox, doc);
    if (!question) continue;

    const answer = resolveAcknowledgmentAnswer(question, enriched, company);
    if (!answer || !/^yes$/i.test(answer)) continue;

    if (fillCheckbox(checkbox, answer)) {
      filled++;
    }
  }

  return filled;
}

function normalizeDemographicOption(text: string): string {
  return text.replace(/\s+/g, ' ').trim().toLowerCase();
}

function demographicOptionMatches(optionLabel: string, profileValue: string): boolean {
  const option = normalizeDemographicOption(optionLabel);
  const value = normalizeDemographicOption(profileValue);
  if (!option || !value) return false;
  if (option === value) return true;
  if ((value === 'male' || value === 'man') && (option === 'male' || option === 'man')) return true;
  if ((value === 'female' || value === 'woman') && (option === 'female' || option === 'woman')) return true;
  return option.includes(value) || value.includes(option);
}

/** Microsoft-style EEO checkbox groups (gender identity, race/ethnicity). */
async function fillDemographicCheckboxes(profile: UserProfile, doc: Document): Promise<number> {
  const enriched = enrichProfile(profile);
  let filled = 0;

  for (const checkbox of Array.from(doc.querySelectorAll('input[type="checkbox"]')) as HTMLInputElement[]) {
    if (checkbox.checked) continue;

    const groupQuestion = getFieldGroupQuestion(checkbox, doc);
    if (!groupQuestion) continue;

    const normalizedQuestion = groupQuestion.replace(/\s+/g, ' ').trim().toLowerCase();
    const optionLabel = getLabelText(checkbox, doc) || checkbox.value || '';
    if (!optionLabel) continue;

    let targetValue = '';
    if (/gender identity|describe your gender/.test(normalizedQuestion)) {
      targetValue = enriched.gender || '';
    } else if (/racial|ethnic background|describe your racial/.test(normalizedQuestion)) {
      targetValue = enriched.raceEthnicity || '';
    } else if (/sexual orientation|describe your sexual/.test(normalizedQuestion)) {
      targetValue = enriched.sexualOrientation || '';
    }

    if (!targetValue || !demographicOptionMatches(optionLabel, targetValue)) continue;
    if (fillCheckbox(checkbox, 'Yes')) {
      filled++;
    }
  }

  return filled;
}

export function resolveFillValue(
  classified: ClassifiedField,
  overrides?: Record<string, string>
): string {
  const override = overrides?.[classified.id]?.trim();
  if (override) return override;

  const proposed = classified.proposedValue?.trim() || '';
  if (proposed) return proposed;

  if (classified.canonicalKey === 'resume') return RESUME_MARKER;
  if (classified.canonicalKey === 'coverLetter') return COVER_MARKER;

  return '';
}

export async function applyFieldFill(
  field: ScannedField,
  value: string,
  profile: UserProfile
): Promise<boolean> {
  const trimmed = value?.trim();
  if (!trimmed) return false;

  if (trimmed === RESUME_MARKER || trimmed === COVER_MARKER) {
    const fileData =
      trimmed === COVER_MARKER ? profile.coverLetter : profile.resume;
    if (!fileData) return false;

    const fileInput =
      field.type === 'file' && field.element instanceof HTMLInputElement
        ? field.element
        : findNearbyFileInput(field.element);

    if (!fileInput) return false;
    fillFileInput(fileInput, fileData);
    return true;
  }

  if (field.type === 'file') {
    if (!(field.element instanceof HTMLInputElement)) return false;
    const fileData = (field.labelText || '').toLowerCase().includes('cover')
      ? profile.coverLetter
      : profile.resume;
    if (!fileData) return false;
    fillFileInput(field.element, fileData);
    return true;
  }

  if (field.type === 'select') {
    const didFill = await fillSelect(resolveSelectElement(field.element), trimmed);
    await new Promise((r) => setTimeout(r, 150));
    return didFill;
  }

  if (field.type === 'radio' && field.element instanceof HTMLInputElement) {
    fillRadio(field.element, trimmed, document);
    return true;
  }

  if (field.type === 'checkbox' && field.element instanceof HTMLInputElement) {
    return fillCheckbox(field.element, trimmed);
  }

  if (
    (field.type === 'text' || field.type === 'textarea') &&
    (field.element instanceof HTMLInputElement || field.element instanceof HTMLTextAreaElement)
  ) {
    return fillTextOrTextArea(field.element, trimmed);
  }

  return false;
}

async function fillRemainingEmptyFields(
  profile: UserProfile,
  doc: Document = document
): Promise<number> {
  const enriched = enrichProfile(profile);
  let extraFilled = 0;

  if (!isResumeAttached(doc)) {
    const attached = await attachResumeIfNeeded(enriched, doc);
    if (attached) {
      extraFilled++;
      await new Promise((r) => setTimeout(r, RESUME_PARSE_WAIT_MS));
      extraFilled += await fillRipplingDataInputFields(enriched, doc);
    }
  }

  const freshFields = scanPage(doc);

  const isUnfilled = (field: ScannedField): boolean => {
    const el = field.element;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;

    if (field.type === 'select') {
      if (el instanceof HTMLSelectElement) {
        const selected = el.options[el.selectedIndex];
        const optText = selected?.text?.trim() || '';
        if (!optText || /^(select\s*one|select\.\.\.|select|search|textbox|--|none)$/i.test(optText)) {
          return true;
        }
        return false;
      }

      const text = (el.textContent || '').trim();
      const inputVal =
        el instanceof HTMLInputElement ? el.value?.trim() : '';
      if (inputVal) return false;
      if (text && !/^(select\.\.\.|select|search|textbox)$/i.test(text)) return false;
      return true;
    }

    if (field.type === 'radio' && el instanceof HTMLInputElement) {
      const name = el.name;
      if (!name) return !el.checked;
      const group = doc.querySelectorAll<HTMLInputElement>(`input[type="radio"][name="${CSS.escape(name)}"]`);
      return !Array.from(group).some((r) => r.checked);
    }

    if (
      (field.type === 'text' || field.type === 'textarea') &&
      (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)
    ) {
      if (['hidden', 'file', 'submit', 'button'].includes(el.type)) return false;
      return !el.value?.trim();
    }

    return false;
  };

  for (const field of freshFields) {
    if (!isUnfilled(field)) continue;
    if (!shouldAutofillField(field, doc)) continue;

    const label = getLabelText(field.element, doc);
    if (field.type === 'select' && COMBOBOX_LABEL_RESOLVERS.some((entry) => entry.test(label))) {
      if (!isComboboxUnfilled(field.element)) continue;
    }

    const inferred = inferRemainingValue(field, enriched);
    if (!inferred.value) continue;
    if (field.type === 'select' && !SELECT_INFER_RE.test(inferred.reason)) continue;

    const ripplingInput =
      field.dataInput || field.element.getAttribute('data-input') || '';
    if (ripplingInput) {
      const expected = RIPPLING_DATA_INPUT_TO_CANONICAL[ripplingInput];
      if (expected && inferred.canonicalKey && expected !== inferred.canonicalKey) continue;
      if (expected && !isComboboxUnfilled(field.element)) continue;
    }

    const didFill = await applyFieldFill(field, inferred.value, enriched);
    if (didFill) extraFilled++;
    await new Promise((r) => setTimeout(r, 120));
  }

  return extraFilled;
}

export interface AutofillSkippedField {
  label: string;
  reason: string;
  fieldId: string;
  canonicalKey?: string;
}

export interface AutofillGaps {
  missingInProfile: string[];
  stillEmptyOnPage: string[];
  resumeMissing: boolean;
  resumeNotAttached: boolean;
}

export interface AutofillResult {
  filledCount: number;
  errors: { label: string; error: string; fieldId?: string }[];
  skippedFields: AutofillSkippedField[];
  gaps: AutofillGaps;
  diagnostics: FieldDiagnostic[];
}

function normalizeLabelKey(label: string): string {
  return label.replace(/\*+$/, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function findFieldByLabel(fields: ScannedField[], label: string): ScannedField | undefined {
  const key = normalizeLabelKey(label);
  if (!key) return undefined;

  return fields.find((field) => {
    const candidates = [field.labelText, field.name, field.placeholder, field.htmlId].filter(Boolean);
    return candidates.some((candidate) => {
      const candidateKey = normalizeLabelKey(candidate);
      return candidateKey === key || candidateKey.includes(key) || key.includes(candidateKey);
    });
  });
}

function inferCanonicalKeyFromLabel(label: string): string | undefined {
  const normalized = normalizeLabelKey(label);
  if (/currently located|where.*located|where.*live|work location/.test(normalized)) {
    return 'location';
  }
  if (/legally authorized|authorized to work|work authorization|right to work/.test(normalized)) {
    return 'workAuthorization';
  }
  if (/sponsor|visa|immigration-related employment benefit/.test(normalized)) {
    return 'sponsorship';
  }
  if (/arbitration|agreement|acknowledge|consent/.test(normalized)) {
    return 'agreement';
  }
  return undefined;
}

function buildSkippedFields(
  diagnostics: FieldDiagnostic[],
  fields: ScannedField[],
  doc: Document
): AutofillSkippedField[] {
  const skipped: AutofillSkippedField[] = [];
  const seen = new Set<string>();

  for (const diagnostic of diagnostics) {
    if (
      diagnostic.category !== 'still_empty' &&
      diagnostic.category !== 'fill_failed' &&
      diagnostic.category !== 'missing_profile_value'
    ) {
      continue;
    }

    const label = diagnostic.label || 'Unnamed field';
    const labelKey = normalizeLabelKey(label);
    if (seen.has(labelKey)) continue;
    seen.add(labelKey);

    const field = findFieldByLabel(fields, label);
    if (field && hasFieldDisplayValue(field, doc)) continue;

    const fieldId = field?.id || '';
    if (field) {
      stampFieldMarker(field.element, fieldId);
    }

    const canonicalKey = diagnostic.canonicalKey || inferCanonicalKeyFromLabel(label);

    skipped.push({
      label,
      reason: diagnostic.reason,
      fieldId,
      canonicalKey
    });
  }

  return skipped;
}

export function summarizeAutofillGaps(profile: UserProfile, doc: Document = document): AutofillGaps {
  const missingInProfile: string[] = [];
  if (!profile.firstName?.trim()) missingInProfile.push('first name');
  if (!profile.lastName?.trim()) missingInProfile.push('last name');
  if (!profile.email?.trim()) missingInProfile.push('email');
  if (!profile.phone?.trim()) missingInProfile.push('phone');
  if (!profile.resume) missingInProfile.push('resume file');

  const stillEmptyOnPage: string[] = [];
  const checkInput = (selector: string, label: string) => {
    const input = doc.querySelector(selector) as HTMLInputElement | null;
    if (input && input.getBoundingClientRect().width > 0 && !input.value?.trim()) {
      stillEmptyOnPage.push(label);
    }
  };

  checkInput('input[data-input="first_name"]', 'first name');
  checkInput('input[data-input="last_name"]', 'last name');
  checkInput('input[data-input="email"]', 'email');
  checkInput('input[data-input="phone_number"]', 'phone');

  return {
    missingInProfile,
    stillEmptyOnPage,
    resumeMissing: !profile.resume,
    resumeNotAttached: !isResumeAttached(doc)
  };
}

export function formatAutofillGapMessage(gaps: AutofillGaps): string | null {
  if (gaps.resumeMissing) {
    return 'Upload resume in Dashboard';
  }
  if (gaps.missingInProfile.length >= 2) {
    return 'Complete profile in Dashboard';
  }
  if (gaps.stillEmptyOnPage.includes('first name') || gaps.stillEmptyOnPage.includes('email')) {
    if (gaps.missingInProfile.includes('first name') || gaps.missingInProfile.includes('email')) {
      return 'Add name & email in Dashboard';
    }
    return 'Contact fields did not fill — retry';
  }
  if (gaps.resumeNotAttached && !gaps.resumeMissing) {
    return 'Resume upload failed — retry';
  }
  return null;
}

export async function executeClassifiedAutofill(
  classified: ClassifiedField[],
  cachedFields: ScannedField[],
  profile: UserProfile,
  overrides?: Record<string, string>,
  doc: Document = document,
  operationId?: string,
  company?: string
): Promise<AutofillResult> {
  const enriched = enrichProfile(profile);
  let filledCount = 0;
  const errors: { label: string; error: string }[] = [];
  const diagnostics: FieldDiagnostic[] = collectClassificationDiagnostics(classified, doc);
  const filledLabels = new Set<string>();
  const pageUrl = doc.location?.href;

  const jobs = classified
    .map((item) => {
      const cached = cachedFields.find((f) => f.id === item.id);
      if (!cached) return null;
      if (!shouldAutofillField(cached, doc)) return null;

      const value = resolveFillValue(item, overrides);
      if (!value) return null;

      return {
        cached,
        value: value || RESUME_MARKER,
        confidence: item.confidence,
        canonicalKey: item.canonicalKey
      };
    })
    .filter(
      (job): job is {
        cached: ScannedField;
        value: string;
        confidence: 'high' | 'medium' | 'low';
        canonicalKey?: string;
      } => job !== null
    )
    .sort(
      (a, b) =>
        autofillFieldPriority(a.cached.type, a.canonicalKey) -
        autofillFieldPriority(b.cached.type, b.canonicalKey)
    );

  traceStep(operationId, 'autofill', 'jobs_prepared', 'autofill:runner', {
    jobCount: jobs.length
  });

  traceStep(operationId, 'autofill', 'resume_attach_start', 'autofill:runner');
  const resumeAttached = await attachResumeIfNeeded(enriched, doc);
  if (resumeAttached) {
    filledCount++;
    traceStep(operationId, 'autofill', 'resume_attached', 'autofill:runner');
    await new Promise((r) => setTimeout(r, RESUME_PARSE_WAIT_MS));
  } else {
    traceStep(operationId, 'autofill', 'resume_skipped', 'autofill:runner');
  }

  // Resume parse re-renders Rippling — re-scan so select element refs stay valid.
  traceStep(operationId, 'autofill', 'post_resume_rescan', 'autofill:runner');
  let freshFields = scanPage(doc);

  traceStep(operationId, 'autofill', 'rippling_data_inputs_start', 'autofill:runner');
  filledCount += await fillRipplingDataInputFields(enriched, doc);
  traceStep(operationId, 'autofill', 'labeled_comboboxes_start', 'autofill:runner');
  filledCount += await fillLabeledComboboxes(enriched, doc);
  traceStep(operationId, 'autofill', 'labeled_radio_groups_start', 'autofill:runner');
  filledCount += await fillLabeledRadioGroups(enriched, doc, company);
  traceStep(operationId, 'autofill', 'acknowledgment_checkboxes_start', 'autofill:runner');
  filledCount += await fillAcknowledgmentCheckboxes(enriched, doc, company);
  filledCount += await fillDemographicCheckboxes(enriched, doc);
  if (fillCustomRadios(enriched.smsConsent || APPLICATION_FIELD_DEFAULTS.smsConsent, doc)) {
    filledCount++;
    traceStep(operationId, 'autofill', 'sms_consent_filled', 'autofill:runner');
  }

  for (const { cached, value, confidence, canonicalKey } of jobs) {
    if (canonicalKey === 'resume' || canonicalKey === 'coverLetter') continue;
    if (canonicalKey === 'smsConsent') continue;
    const fieldLabel = cached.labelText || cached.name || canonicalKey || 'Unnamed field';
    const field = resolveFreshField(cached, freshFields);
    if (!field) {
      traceStep(operationId, 'autofill', 'field_skipped', 'autofill:runner', {
        label: fieldLabel,
        reason: 'not_found_after_rescan',
        canonicalKey
      });
      diagnostics.push({
        category: 'skipped_by_rule',
        label: cached.labelText || cached.name || 'Unnamed field',
        fieldType: cached.type,
        reason: 'Field not found after DOM re-scan',
        canonicalKey
      });
      continue;
    }
    if (field.type === 'select' && canonicalKey && EEO_CANONICAL_KEYS.has(canonicalKey)) {
      traceStep(operationId, 'autofill', 'field_skipped', 'autofill:runner', {
        label: fieldLabel,
        reason: 'eeo_combobox_pass',
        canonicalKey
      });
      diagnostics.push({
        category: 'skipped_by_rule',
        label: field.labelText || field.name || 'Unnamed field',
        fieldType: field.type,
        reason: 'EEO select handled by labeled combobox pass',
        canonicalKey
      });
      continue;
    }

    const ripplingInput =
      field.dataInput || field.element.getAttribute('data-input') || '';
    if (ripplingInput && canonicalKey) {
      const expected = RIPPLING_DATA_INPUT_TO_CANONICAL[ripplingInput];
      if (expected && expected !== canonicalKey) {
        traceStep(operationId, 'autofill', 'field_skipped', 'autofill:runner', {
          label: fieldLabel,
          reason: 'rippling_data_input_mismatch',
          canonicalKey,
          dataInput: ripplingInput
        });
        diagnostics.push({
          category: 'skipped_by_rule',
          label: field.labelText || field.name || 'Unnamed field',
          fieldType: field.type,
          reason: `Rippling data-input "${ripplingInput}" expects "${expected}", not "${canonicalKey}"`,
          canonicalKey
        });
        continue;
      }
    }

    if (
      (field.type === 'text' || field.type === 'textarea') &&
      field.dataInput &&
      field.dataInput in RIPPLING_DATA_INPUT_MAP
    ) {
      traceStep(operationId, 'autofill', 'field_skipped', 'autofill:runner', {
        label: fieldLabel,
        reason: 'rippling_text_pass',
        canonicalKey
      });
      diagnostics.push({
        category: 'skipped_by_rule',
        label: field.labelText || field.name || 'Unnamed field',
        fieldType: field.type,
        reason: 'Rippling text field handled by data-input pass',
        canonicalKey
      });
      continue;
    }
    try {
      traceStep(operationId, 'autofill', 'field_fill_start', 'autofill:runner', {
        label: fieldLabel,
        fieldType: field.type,
        canonicalKey
      });
      const didFill = await applyFieldFill(field, value, enriched);
      if (didFill) {
        filledCount++;
        highlightField(field.element, confidence);
        const label = (field.labelText || field.name || '').toLowerCase();
        if (label) filledLabels.add(label);
        traceStep(operationId, 'autofill', 'field_fill_success', 'autofill:runner', {
          label: fieldLabel,
          fieldType: field.type,
          canonicalKey
        });
      } else {
        traceStep(operationId, 'autofill', 'field_fill_failed', 'autofill:runner', {
          label: fieldLabel,
          fieldType: field.type,
          canonicalKey,
          reason: 'fill_returned_false'
        });
        diagnostics.push({
          category: 'fill_failed',
          label: field.labelText || field.name || 'Unnamed field',
          fieldType: field.type,
          reason: `Fill returned false for value "${value.slice(0, 80)}"`,
          canonicalKey,
          confidence
        });
      }
    } catch (err: any) {
      console.error(`[JobFill] Failed to autofill field: ${field.labelText}`, err);
      traceStep(operationId, 'autofill', 'field_fill_error', 'autofill:runner', {
        label: fieldLabel,
        fieldType: field.type,
        canonicalKey,
        error: err.message
      });
      logToServer({
        level: 'error',
        source: 'autofill:field',
        message: `Failed to fill "${field.labelText || field.name || 'field'}"`,
        stack: err.stack,
        detail: {
          error: err.message,
          fieldType: field.type,
          canonicalKey,
          label: field.labelText
        },
        url: doc.location?.href
      });
      errors.push({
        label: field.labelText || field.name || 'Unnamed Field',
        error: err.message
      });
    }
  }

  traceStep(operationId, 'autofill', 'remaining_empty_start', 'autofill:runner');
  filledCount += await fillWorkExperienceSections(enriched, doc, operationId);
  const extraFilled = await fillRemainingEmptyFields(enriched, doc);
  filledCount += extraFilled;
  traceStep(operationId, 'autofill', 'remaining_empty_end', 'autofill:runner', { extraFilled });

  traceStep(operationId, 'autofill', 'final_rescan', 'autofill:runner');
  freshFields = scanPage(doc);
  diagnostics.push(...collectStillEmptyDiagnostics(freshFields, doc, filledLabels));

  const skippedFields = buildSkippedFields(diagnostics, freshFields, doc);
  for (const skipped of skippedFields) {
    if (errors.some((entry) => normalizeLabelKey(entry.label) === normalizeLabelKey(skipped.label))) {
      continue;
    }
    if (skipped.reason === 'Still empty after autofill') continue;
    if (isOptionalAddressField(skipped.label)) continue;
    if (/personnel number|\bpern\b/i.test(skipped.label)) continue;
    errors.push({
      label: skipped.label,
      error: skipped.reason,
      fieldId: skipped.fieldId
    });
  }

  await persistSkippedFieldValues(enriched, skippedFields, doc);
  await captureAddressFromPage(doc, enriched);

  void logFieldDiagnostics(diagnostics, pageUrl);

  traceStep(operationId, 'autofill', 'runner_complete', 'autofill:runner', {
    filledCount,
    errorCount: errors.length,
    skippedCount: skippedFields.length
  });

  return { filledCount, errors, skippedFields, gaps: summarizeAutofillGaps(enriched, doc), diagnostics };
}

export async function runFullPageAutofill(
  profile: UserProfile,
  overrides?: Record<string, string>,
  company?: string,
  domain?: string,
  doc: Document = document,
  operationId?: string
): Promise<AutofillResult> {
  traceStep(operationId, 'autofill', 'scan_page', 'autofill:runner');
  const fields = scanPage(doc);
  const enriched = enrichProfile(profile);
  traceStep(operationId, 'autofill', 'classify_start', 'autofill:runner', { fieldCount: fields.length });
  const classified = await classifyFields(fields, enriched, company, domain);
  traceStep(operationId, 'autofill', 'classify_end', 'autofill:runner', {
    classifiedCount: classified.length
  });
  return executeClassifiedAutofill(classified, fields, enriched, overrides, doc, operationId, company);
}
