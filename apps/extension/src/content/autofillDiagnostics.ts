import { ScannedField, getLabelText } from './domScanner';
import { ClassifiedField } from './fieldClassifier';
import { AutofillLogConfig, getAutofillLogConfig } from '../shared/autofillLogConfig';
import { logToServer } from '../shared/serverLog';
import { isFillableFieldType } from './fieldInference';

export type FieldDiagnosticCategory =
  | 'unrecognized'
  | 'missing_profile_value'
  | 'fill_failed'
  | 'still_empty'
  | 'skipped_by_rule';

export interface FieldDiagnostic {
  category: FieldDiagnosticCategory;
  label: string;
  fieldType: ScannedField['type'];
  reason: string;
  canonicalKey?: string;
  confidence?: string;
  htmlId?: string;
  name?: string;
}

function isVisibleFillable(field: ScannedField, doc: Document): boolean {
  if (!isFillableFieldType(field.type)) return false;
  const el = field.element;
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  if (field.type === 'file') return false;
  const label = (field.labelText || getLabelText(el, doc) || '').toLowerCase();
  if (/password|ssn|social security|credit card/.test(label)) return false;
  return true;
}

export function isFieldUnfilled(field: ScannedField, doc: Document): boolean {
  const el = field.element;
  if (!isVisibleFillable(field, doc)) return false;

  if (field.type === 'select') {
    const text = (el.textContent || '').trim();
    const inputVal = el instanceof HTMLInputElement ? el.value?.trim() : '';
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
}

export function collectClassificationDiagnostics(
  classified: ClassifiedField[],
  doc: Document
): FieldDiagnostic[] {
  const diagnostics: FieldDiagnostic[] = [];

  for (const item of classified) {
    const field = item.scannedField;
    if (!isVisibleFillable(field, doc)) continue;

    const label = field.labelText || field.name || field.placeholder || field.htmlId || 'Unnamed field';
    const hasValue = Boolean(item.proposedValue?.trim());

    if (!item.canonicalKey && !hasValue) {
      diagnostics.push({
        category: 'unrecognized',
        label,
        fieldType: field.type,
        reason: item.reason || 'No classifier match',
        confidence: item.confidence
      });
      continue;
    }

    if (item.canonicalKey && !hasValue && item.canonicalKey !== 'resume' && item.canonicalKey !== 'coverLetter') {
      diagnostics.push({
        category: 'missing_profile_value',
        label,
        fieldType: field.type,
        reason: item.reason || `No value in profile for "${item.canonicalKey}"`,
        canonicalKey: item.canonicalKey,
        confidence: item.confidence
      });
    }
  }

  return diagnostics;
}

export function collectStillEmptyDiagnostics(
  fields: ScannedField[],
  doc: Document,
  filledLabels: Set<string>
): FieldDiagnostic[] {
  const diagnostics: FieldDiagnostic[] = [];

  for (const field of fields) {
    if (!isFieldUnfilled(field, doc)) continue;

    const label = field.labelText || field.name || field.placeholder || field.htmlId || 'Unnamed field';
    if (filledLabels.has(label.toLowerCase())) continue;

    diagnostics.push({
      category: 'still_empty',
      label,
      fieldType: field.type,
      reason: 'Still empty after autofill',
      htmlId: field.htmlId,
      name: field.name
    });
  }

  return diagnostics;
}

function configAllows(category: FieldDiagnosticCategory, config: AutofillLogConfig): boolean {
  switch (category) {
    case 'unrecognized':
      return config.unrecognizedFields;
    case 'missing_profile_value':
      return config.missingProfileValue;
    case 'fill_failed':
      return config.fillReturnedFalse;
    case 'still_empty':
      return config.stillEmpty;
    case 'skipped_by_rule':
      return config.skippedByRule;
    default:
      return false;
  }
}

export function logFieldDiagnostic(diagnostic: FieldDiagnostic, url?: string): void {
  void getAutofillLogConfig().then((config) => {
    if (!configAllows(diagnostic.category, config)) return;

    const level =
      diagnostic.category === 'unrecognized' || diagnostic.category === 'still_empty'
        ? 'warn'
        : 'info';

    logToServer({
      level,
      source: 'autofill:diagnostic',
      message: `[${diagnostic.category}] ${diagnostic.label}`,
      detail: {
        category: diagnostic.category,
        fieldType: diagnostic.fieldType,
        reason: diagnostic.reason,
        canonicalKey: diagnostic.canonicalKey,
        confidence: diagnostic.confidence,
        htmlId: diagnostic.htmlId,
        name: diagnostic.name
      },
      url
    });
  });
}

export async function logFieldDiagnostics(
  diagnostics: FieldDiagnostic[],
  url?: string
): Promise<void> {
  const config = await getAutofillLogConfig();
  const filtered = diagnostics.filter((d) => configAllows(d.category, config));
  if (!filtered.length) return;

  for (const diagnostic of filtered) {
    logFieldDiagnostic(diagnostic, url);
  }

  const byCategory = filtered.reduce<Record<string, number>>((acc, d) => {
    acc[d.category] = (acc[d.category] || 0) + 1;
    return acc;
  }, {});

  logToServer({
    level: 'warn',
    source: 'autofill:diagnostic',
    message: `Autofill diagnostics: ${filtered.length} field issue(s)`,
    detail: {
      counts: byCategory,
      fields: filtered.map((d) => ({
        category: d.category,
        label: d.label,
        reason: d.reason,
        canonicalKey: d.canonicalKey
      }))
    },
    url
  });
}
