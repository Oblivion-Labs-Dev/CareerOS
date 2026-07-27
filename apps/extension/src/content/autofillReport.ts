import { FieldDiagnostic, FieldDiagnosticCategory } from './autofillDiagnostics';
import { ScannedField } from './domScanner';
import { stampFieldMarker } from './fieldMarker';
import { hasFieldDisplayValue } from './fieldValue';
import { logToServer } from '../shared/serverLog';

export interface AutofillSkippedField {
  label: string;
  reason: string;
  fieldId: string;
  canonicalKey?: string;
  category?: FieldDiagnosticCategory | 'error';
}

export interface AutofillIssueReport {
  filledCount: number;
  issueCount: number;
  counts: Partial<Record<FieldDiagnosticCategory | 'error', number>>;
  skippedFields: AutofillSkippedField[];
  summary: string;
}

const USER_FACING_CATEGORIES = new Set<FieldDiagnosticCategory>([
  'unrecognized',
  'missing_profile_value',
  'fill_failed',
  'still_empty',
]);

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

function formatSkippedReason(category: FieldDiagnosticCategory, reason: string): string {
  switch (category) {
    case 'unrecognized':
      return `Unidentified — ${reason || 'no profile mapping'}`;
    case 'missing_profile_value':
      return `Missing in profile — ${reason || 'add this answer in Dashboard'}`;
    case 'fill_failed':
      return `Could not fill — ${reason || 'value did not apply'}`;
    case 'still_empty':
      return reason || 'Still empty after autofill';
    default:
      return reason;
  }
}

function bumpCount(
  counts: Partial<Record<FieldDiagnosticCategory | 'error', number>>,
  category: FieldDiagnosticCategory | 'error'
) {
  counts[category] = (counts[category] || 0) + 1;
}

export function buildAutofillIssueReport(
  diagnostics: FieldDiagnostic[],
  fields: ScannedField[],
  doc: Document,
  errors: { label: string; error: string; fieldId?: string }[],
  filledCount: number
): AutofillIssueReport {
  const skipped: AutofillSkippedField[] = [];
  const seen = new Set<string>();
  const counts: Partial<Record<FieldDiagnosticCategory | 'error', number>> = {};

  for (const diagnostic of diagnostics) {
    if (!USER_FACING_CATEGORIES.has(diagnostic.category)) continue;

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

    bumpCount(counts, diagnostic.category);
    skipped.push({
      label,
      reason: formatSkippedReason(diagnostic.category, diagnostic.reason),
      fieldId,
      canonicalKey: diagnostic.canonicalKey || inferCanonicalKeyFromLabel(label),
      category: diagnostic.category,
    });
  }

  for (const err of errors) {
    const label = err.label || 'Unnamed field';
    const labelKey = normalizeLabelKey(label);
    if (seen.has(labelKey)) continue;
    seen.add(labelKey);

    bumpCount(counts, 'error');
    skipped.push({
      label,
      reason: `Error — ${err.error}`,
      fieldId: err.fieldId || '',
      category: 'error',
    });
  }

  const issueCount = skipped.length;
  const summary = formatIssueSummary(counts, issueCount);

  return {
    filledCount,
    issueCount,
    counts,
    skippedFields: skipped,
    summary,
  };
}

export function formatIssueSummary(
  counts: Partial<Record<FieldDiagnosticCategory | 'error', number>>,
  issueCount: number
): string {
  if (!issueCount) return '';

  const parts: string[] = [];
  if (counts.unrecognized) parts.push(`${counts.unrecognized} unidentified`);
  if (counts.still_empty) parts.push(`${counts.still_empty} unfilled`);
  if (counts.missing_profile_value) parts.push(`${counts.missing_profile_value} missing profile`);
  if (counts.fill_failed) parts.push(`${counts.fill_failed} could not fill`);
  if (counts.error) parts.push(`${counts.error} error${counts.error === 1 ? '' : 's'}`);

  return parts.length ? parts.join(' · ') : `${issueCount} need review`;
}

export function logAutofillIssueReport(
  source: string,
  report: AutofillIssueReport,
  url?: string
): void {
  if (!report.issueCount) return;

  for (const field of report.skippedFields) {
    const level = field.category === 'error' ? 'error' : 'warn';
    logToServer({
      level,
      source: `${source}:skipped-field`,
      message: `${field.label}: ${field.reason}`,
      detail: {
        category: field.category,
        fieldId: field.fieldId,
        canonicalKey: field.canonicalKey,
      },
      url,
    });
  }

  logToServer({
    level: 'warn',
    source: `${source}:issue-report`,
    message: `Autofill left ${report.issueCount} field issue(s) — ${report.summary}`,
    detail: {
      filledCount: report.filledCount,
      issueCount: report.issueCount,
      counts: report.counts,
      fields: report.skippedFields.map((field) => ({
        label: field.label,
        reason: field.reason,
        category: field.category,
        fieldId: field.fieldId,
        canonicalKey: field.canonicalKey,
      })),
    },
    url,
  });
}
