import { scanPage, ScannedField, getLabelText, getFieldGroupQuestion, getComboboxLabelCandidates, isGreenhouseSelectPhantom, isExtensionUiElement } from './domScanner';
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
  isGreenhousePhoneCountryCombobox,
  resolvePhoneCountryFillValue,
} from './fieldInference';
import { isPlaceholderSelectOption } from '../shared/usStates';
import { APPLICATION_FIELD_DEFAULTS } from '../shared/applicationDefaults';
import { logToServer } from '../shared/serverLog';
import { traceStep } from '../shared/actionTrace';
import {
  collectClassificationDiagnostics,
  collectStillEmptyDiagnostics,
  FieldDiagnostic,
  logFieldDiagnostics
} from './autofillDiagnostics';
import { fillWorkExperienceSections } from './workExperienceAutofill';
import { matchScreeningAnswer } from '../shared/screeningAnswers';
import { persistSkippedFieldValues } from './skippedFieldProfile';
import { shouldAutofillField } from './fieldRequired';
import { addressValueForKey, captureAddressFromPage } from '../profile/addressProfile';
import { runAtsAutofill } from './atsAutofillEngine';
import { runMultiStepAtsPass } from './atsStepRunner';
import { fillWorkExperienceRepeaters } from './workExperienceRepeater';
import { rememberAutofillMappings } from '../learning/fieldMappingMemory';
import { generateId } from '../shared/id';
import {
  detectFileInputUploadKind,
  detectUploadKindFromHint,
  findFileInputForKind,
  isUploadKindAttached,
  zoneTextIndicatesKind,
} from './fileUploadDetection';
import {
  buildAutofillIssueReport,
  logAutofillIssueReport,
  type AutofillIssueReport,
  type AutofillSkippedField,
} from './autofillReport';
import { isSelectOptionCommitted } from './selectVerification';
import { resolveComboboxFillValue, resolveComboboxFillValueFromLabels } from './comboboxValueResolver';

export type { AutofillSkippedField, AutofillIssueReport };

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
  return isUploadKindAttached('resume', doc);
}

async function attachFileForKind(
  profile: UserProfile,
  kind: 'resume' | 'coverLetter',
  doc: Document
): Promise<boolean> {
  const fileData = kind === 'coverLetter' ? profile.coverLetter : profile.resume;
  if (!fileData || isUploadKindAttached(kind, doc)) return false;

  const matchedInput = findFileInputForKind(kind, doc);
  if (matchedInput && !isUploadKindAttached(kind, doc)) {
    fillFileInput(matchedInput, fileData);
    return true;
  }

  const dropZones = Array.from(doc.querySelectorAll('div, section, label, button, span')) as HTMLElement[];
  for (const zone of dropZones) {
    const text = zone.textContent?.replace(/\s+/g, ' ').trim() || '';
    if (!zoneTextIndicatesKind(text, kind)) continue;
    const nearby = findNearbyFileInput(zone, doc);
    if (!nearby) continue;
    if (detectFileInputUploadKind(nearby, doc) === (kind === 'resume' ? 'coverLetter' : 'resume')) {
      continue;
    }
    fillFileInput(nearby, fileData);
    return true;
  }

  return false;
}

async function attachResumeIfNeeded(profile: UserProfile, doc: Document): Promise<boolean> {
  return attachFileForKind(profile, 'resume', doc);
}

async function attachCoverLetterIfNeeded(profile: UserProfile, doc: Document): Promise<boolean> {
  return attachFileForKind(profile, 'coverLetter', doc);
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

function isComboboxUnfilled(el: HTMLElement): boolean {
  return !isSelectOptionCommitted(el);
}

/** Fill native HTML select EEO dropdowns (Greenhouse, Lever, etc.). */
async function fillLabeledNativeSelects(profile: UserProfile, doc: Document): Promise<number> {
  const enriched = enrichProfile(profile);
  let filled = 0;

  for (const select of Array.from(doc.querySelectorAll('select')) as HTMLSelectElement[]) {
    if (isExtensionUiElement(select)) continue;
    if (!isComboboxUnfilled(select)) continue;

    const label = getLabelText(select, doc);
    if (!label) continue;

    const value = resolveComboboxFillValue(label, enriched);
    if (!value) continue;

    const didFill = await fillSelect(select, value);
    if (didFill) filled++;
    await new Promise((r) => setTimeout(r, 150));
  }

  return filled;
}

/** Fill Rippling/custom comboboxes by walking fresh DOM labels (survives resume re-render). */
const MAX_LABELED_COMBOBOXES = 35;

function isCustomSelectField(field: ScannedField): boolean {
  return field.type === 'select' && !(field.element instanceof HTMLSelectElement);
}

/** Scroll long forms so lazy-rendered Greenhouse sections (screening/EEO) mount before combobox pass. */
async function scrollFormToLoadFields(doc: Document): Promise<void> {
  const win = doc.defaultView;
  if (!win) return;
  const step = Math.max(220, Math.floor(win.innerHeight * 0.8));
  for (let y = 0; y < doc.body.scrollHeight; y += step) {
    win.scrollTo(0, y);
    await new Promise((r) => setTimeout(r, 90));
  }
  win.scrollTo(0, doc.body.scrollHeight);
  await new Promise((r) => setTimeout(r, 250));
  win.scrollTo(0, 0);
  await new Promise((r) => setTimeout(r, 120));
}

async function fillLabeledComboboxes(
  profile: UserProfile,
  doc: Document,
  company?: string
): Promise<{ filled: number; failures: FieldDiagnostic[] }> {
  const enriched = enrichProfile(profile);
  let filled = 0;
  const failures: FieldDiagnostic[] = [];
  const filledRoots = new Set<HTMLElement>();
  let processed = 0;

  await scrollFormToLoadFields(doc);

  const comboboxes = Array.from(
    doc.querySelectorAll('.select-shell input.select__input[role="combobox"]') as NodeListOf<HTMLElement>
  ).filter((el) => !isExtensionUiElement(el));

  console.log(`[JobFill] fillLabeledComboboxes: ${comboboxes.length} combobox(es) after scroll`);

  for (const combobox of comboboxes) {
    if (processed >= MAX_LABELED_COMBOBOXES) break;
    if (isGreenhouseSelectPhantom(combobox)) continue;
    processed++;
    const root = (combobox.closest('.select-shell') as HTMLElement | null) || combobox;
    if (filledRoots.has(root)) continue;
    if (!isComboboxUnfilled(root)) continue;

    root.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' as ScrollBehavior });
    await new Promise((r) => setTimeout(r, 60));

    const labelCandidates = getComboboxLabelCandidates(combobox, doc);
    const label = labelCandidates[0] || getLabelText(combobox, doc);
    if (!label) continue;

    const value =
      resolveComboboxFillValueFromLabels(labelCandidates, enriched, company) ||
      (isGreenhousePhoneCountryCombobox(combobox) ? resolvePhoneCountryFillValue(enriched) : undefined);

    if (!value) {
      failures.push({
        category: 'unrecognized',
        label,
        fieldType: 'select',
        reason: 'No profile mapping for combobox'
      });
      continue;
    }

    const didFill = await Promise.race<boolean>([
      fillSelect(resolveSelectElement(combobox), value),
      new Promise((resolve) => setTimeout(() => resolve(false), 6_000))
    ]);
    console.log(
      `[JobFill] combobox "${label.slice(0, 72)}" -> ${didFill ? 'filled' : 'failed'} (value: ${value.slice(0, 40)})`
    );
    if (didFill) {
      filledRoots.add(root);
      filled++;
    } else {
      failures.push({
        category: 'fill_failed',
        label,
        fieldType: 'select',
        reason: `Fill returned false for value "${value.slice(0, 80)}"`
      });
    }
    await new Promise((r) => setTimeout(r, 100));
  }

  // Second pass: scroll may mount additional Greenhouse sections after first fills.
  await scrollFormToLoadFields(doc);
  const secondPassComboboxes = Array.from(
    doc.querySelectorAll('.select-shell input.select__input[role="combobox"]') as NodeListOf<HTMLElement>
  );
  for (const combobox of secondPassComboboxes) {
    if (processed >= MAX_LABELED_COMBOBOXES) break;
    const root = (combobox.closest('.select-shell') as HTMLElement | null) || combobox;
    if (filledRoots.has(root) || !isComboboxUnfilled(root)) continue;
    processed++;
    root.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' as ScrollBehavior });
    await new Promise((r) => setTimeout(r, 60));

    const labelCandidates = getComboboxLabelCandidates(combobox, doc);
    const label = labelCandidates[0] || getLabelText(combobox, doc);
    if (!label) continue;

    const value =
      resolveComboboxFillValueFromLabels(labelCandidates, enriched, company) ||
      (isGreenhousePhoneCountryCombobox(combobox) ? resolvePhoneCountryFillValue(enriched) : undefined);

    if (!value) {
      failures.push({ category: 'unrecognized', label, fieldType: 'select', reason: 'No profile mapping for combobox' });
      continue;
    }

    const didFill = await Promise.race<boolean>([
      fillSelect(resolveSelectElement(combobox), value),
      new Promise((resolve) => setTimeout(() => resolve(false), 6_000))
    ]);
    console.log(
      `[JobFill] combobox "${label.slice(0, 72)}" -> ${didFill ? 'filled' : 'failed'} (value: ${value.slice(0, 40)})`
    );
    if (didFill) {
      filledRoots.add(root);
      filled++;
    } else {
      failures.push({
        category: 'fill_failed',
        label,
        fieldType: 'select',
        reason: `Fill returned false for value "${value.slice(0, 80)}"`
      });
    }
    await new Promise((r) => setTimeout(r, 100));
  }

  return { filled, failures };
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
    const hint = `${field.labelText} ${field.placeholder} ${field.name}`;
    const kind = detectUploadKindFromHint(hint);
    if (kind === 'coverLetter') {
      if (!profile.coverLetter) return false;
      fillFileInput(field.element, profile.coverLetter);
      return true;
    }
    if (kind === 'resume') {
      if (!profile.resume) return false;
      fillFileInput(field.element, profile.resume);
      return true;
    }
    return false;
  }

  if (field.type === 'select') {
    const target = resolveSelectElement(field.element);
    const didFill = await fillSelect(target, trimmed);
    await new Promise((r) => setTimeout(r, 150));
    return didFill && isSelectOptionCommitted(target, trimmed);
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
    const el = field.element;
    if (el instanceof HTMLInputElement) {
      const comboboxRoot = el.closest('[role="combobox"]') as HTMLElement | null;
      const isDropdownInput =
        el.getAttribute('role') === 'combobox' ||
        el.getAttribute('aria-autocomplete') === 'list' ||
        el.getAttribute('data-input') === 'select-search-input' ||
        el.getAttribute('aria-haspopup') === 'listbox' ||
        Boolean(comboboxRoot);
      if (isDropdownInput) {
        const target = comboboxRoot || el;
        const didFill = await fillSelect(target, trimmed);
        await new Promise((r) => setTimeout(r, 150));
        return didFill && isSelectOptionCommitted(target, trimmed);
      }
    }
    return fillTextOrTextArea(el, trimmed);
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
        if (!optText || isPlaceholderSelectOption(optText, selected?.value)) {
          return true;
        }
        return false;
      }

      return !isSelectOptionCommitted(el);
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
    if (isCustomSelectField(field)) continue;
    if (!shouldAutofillField(field, doc)) continue;

    const label = getLabelText(field.element, doc);
    if (field.type === 'select' && resolveComboboxFillValue(label, enriched, company)) {
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
  issueReport: AutofillIssueReport;
}

export interface AutofillGaps {
  missingInProfile: string[];
  stillEmptyOnPage: string[];
  resumeMissing: boolean;
  resumeNotAttached: boolean;
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
  const mappingEntries: Parameters<typeof rememberAutofillMappings>[0]['entries'] = [];
  const sessionId = operationId || generateId();
  const pageUrl = doc.location?.href;
  const hostDomain = doc.location?.hostname;

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

  traceStep(operationId, 'autofill', 'cover_attach_start', 'autofill:runner');
  const coverAttached = await attachCoverLetterIfNeeded(enriched, doc);
  if (coverAttached) {
    filledCount++;
    traceStep(operationId, 'autofill', 'cover_attached', 'autofill:runner');
  } else {
    traceStep(operationId, 'autofill', 'cover_skipped', 'autofill:runner');
  }

  // Resume parse re-renders Rippling — re-scan so select element refs stay valid.
  traceStep(operationId, 'autofill', 'post_resume_rescan', 'autofill:runner');
  let freshFields = scanPage(doc);

  traceStep(operationId, 'autofill', 'rippling_data_inputs_start', 'autofill:runner');
  filledCount += await fillRipplingDataInputFields(enriched, doc);
  traceStep(operationId, 'autofill', 'form_scroll_for_lazy_fields', 'autofill:runner');
  await scrollFormToLoadFields(doc);
  traceStep(operationId, 'autofill', 'labeled_comboboxes_start', 'autofill:runner');
  const comboboxResult = await fillLabeledComboboxes(enriched, doc, company);
  filledCount += comboboxResult.filled;
  diagnostics.push(...comboboxResult.failures);
  filledCount += await fillLabeledNativeSelects(enriched, doc);
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
    if (
      field.type === 'select' &&
      canonicalKey &&
      EEO_CANONICAL_KEYS.has(canonicalKey) &&
      !(field.element instanceof HTMLSelectElement)
    ) {
      traceStep(operationId, 'autofill', 'field_skipped', 'autofill:runner', {
        label: fieldLabel,
        reason: 'eeo_combobox_pass',
        canonicalKey
      });
      diagnostics.push({
        category: 'skipped_by_rule',
        label: field.labelText || field.name || 'Unnamed field',
        fieldType: field.type,
        reason: 'Custom EEO combobox handled by labeled combobox pass',
        canonicalKey
      });
      continue;
    }

    if (isCustomSelectField(field) || isGreenhouseSelectPhantom(field.element)) {
      traceStep(operationId, 'autofill', 'field_skipped', 'autofill:runner', {
        label: fieldLabel,
        reason: 'custom_combobox_pass',
        canonicalKey
      });
      diagnostics.push({
        category: 'skipped_by_rule',
        label: field.labelText || field.name || 'Unnamed field',
        fieldType: field.type,
        reason: 'Custom combobox handled by labeled combobox pass',
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
        mappingEntries.push({
          label: field.labelText || field.name || canonicalKey || 'Unnamed field',
          fieldType: field.type,
          canonicalKey,
          value,
          confidence: confidence === 'high' ? 0.92 : confidence === 'medium' ? 0.75 : 0.55,
          source: 'profile',
        });
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

  const issueReport = buildAutofillIssueReport(diagnostics, freshFields, doc, errors, filledCount);
  const skippedFields = issueReport.skippedFields;

  await persistSkippedFieldValues(enriched, skippedFields, doc);
  await captureAddressFromPage(doc, enriched);

  if (mappingEntries.length) {
    await rememberAutofillMappings({
      domain: hostDomain,
      sessionId,
      entries: mappingEntries,
    });
  }

  void logFieldDiagnostics(diagnostics, pageUrl);
  logAutofillIssueReport('autofill:runner', issueReport, pageUrl);

  traceStep(operationId, 'autofill', 'runner_complete', 'autofill:runner', {
    filledCount,
    errorCount: errors.length,
    skippedCount: skippedFields.length,
    issueSummary: issueReport.summary
  });

  return {
    filledCount,
    errors,
    skippedFields,
    gaps: summarizeAutofillGaps(enriched, doc),
    diagnostics,
    issueReport,
  };
}

export async function runFullPageAutofill(
  profile: UserProfile,
  overrides?: Record<string, string>,
  company?: string,
  domain?: string,
  doc: Document = document,
  operationId?: string
): Promise<AutofillResult> {
  traceStep(operationId, 'autofill', 'ats_prefill_start', 'autofill:runner');
  const atsResult = await runAtsAutofill(profile, doc, operationId);
  if (atsResult?.filledCount) {
    traceStep(operationId, 'autofill', 'ats_prefill_done', 'autofill:runner', atsResult);
    await new Promise((resolve) => setTimeout(resolve, 400));
  }

  traceStep(operationId, 'autofill', 'scan_page', 'autofill:runner');
  const fields = scanPage(doc);
  if (!fields.length) {
    traceStep(operationId, 'autofill', 'no_fields', 'autofill:runner');
    return {
      filledCount: 0,
      errors: [],
      skippedFields: [],
      gaps: summarizeAutofillGaps(enrichProfile(profile), doc),
      diagnostics: [],
      issueReport: buildAutofillIssueReport([], [], doc, [], 0)
    };
  }
  const enriched = enrichProfile(profile);
  traceStep(operationId, 'autofill', 'classify_start', 'autofill:runner', { fieldCount: fields.length });
  const classified = await classifyFields(fields, enriched, company, domain || doc.location.hostname);
  traceStep(operationId, 'autofill', 'classify_end', 'autofill:runner', {
    classifiedCount: classified.length
  });
  const result = await executeClassifiedAutofill(classified, fields, enriched, overrides, doc, operationId, company);

  const expFilled = await fillWorkExperienceRepeaters(enriched, doc);
  if (expFilled > 0) {
    result.filledCount += expFilled;
    traceStep(operationId, 'autofill', 'work_exp_repeater', 'autofill:runner', { expFilled });
  }

  const stepsAdvanced = await runMultiStepAtsPass(doc);
  if (stepsAdvanced > 0) {
    traceStep(operationId, 'autofill', 'ats_steps_advanced', 'autofill:runner', { stepsAdvanced });
  }

  return result;
}
