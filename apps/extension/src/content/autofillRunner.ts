import { scanPage, ScannedField, getLabelText } from './domScanner';
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
import { inferRemainingValue, RIPPLING_DATA_INPUT_MAP, RIPPLING_DATA_INPUT_TO_CANONICAL } from './fieldInference';
import { resolvePronounFillValue } from './autofillEngine.matching';
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
  { test: (l) => /\bgender\b/i.test(l), value: (p) => p.gender || APPLICATION_FIELD_DEFAULTS.gender },
  {
    test: (l) => /race|ethnicity/i.test(l),
    value: (p) => p.raceEthnicity || APPLICATION_FIELD_DEFAULTS.raceEthnicity
  },
  { test: (l) => /hispanic|latino/i.test(l), value: (p) => p.hispanic || APPLICATION_FIELD_DEFAULTS.hispanic },
  { test: (l) => /veteran/i.test(l), value: (p) => p.veteran || APPLICATION_FIELD_DEFAULTS.veteran },
  {
    test: (l) => /disability/i.test(l),
    value: (p) => p.disability || APPLICATION_FIELD_DEFAULTS.disability
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

    const resolver = COMBOBOX_LABEL_RESOLVERS.find((entry) => entry.test(label));
    if (!resolver) continue;

    const value = resolver.value(enriched)?.trim();
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
    fillCheckbox(field.element, trimmed);
    return true;
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

export interface AutofillGaps {
  missingInProfile: string[];
  stillEmptyOnPage: string[];
  resumeMissing: boolean;
  resumeNotAttached: boolean;
}

export interface AutofillResult {
  filledCount: number;
  errors: { label: string; error: string }[];
  gaps: AutofillGaps;
  diagnostics: FieldDiagnostic[];
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
  operationId?: string
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

  void logFieldDiagnostics(diagnostics, pageUrl);

  traceStep(operationId, 'autofill', 'runner_complete', 'autofill:runner', {
    filledCount,
    errorCount: errors.length
  });

  return { filledCount, errors, gaps: summarizeAutofillGaps(enriched, doc), diagnostics };
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
  return executeClassifiedAutofill(classified, fields, enriched, overrides, doc, operationId);
}
