import { describe, expect, it } from 'vitest';
import { buildAutofillIssueReport, formatIssueSummary } from './autofillReport';
import type { FieldDiagnostic } from './autofillDiagnostics';

describe('buildAutofillIssueReport', () => {
  const doc = {} as Document;

  it('includes unidentified and unfilled fields in the report', () => {
    const diagnostics: FieldDiagnostic[] = [
      {
        category: 'unrecognized',
        label: 'How did you hear about us?',
        fieldType: 'select',
        reason: 'No classifier match',
      },
      {
        category: 'still_empty',
        label: 'LinkedIn URL',
        fieldType: 'text',
        reason: 'Still empty after autofill',
      },
      {
        category: 'skipped_by_rule',
        label: 'Internal only',
        fieldType: 'text',
        reason: 'Handled elsewhere',
      },
    ];

    const report = buildAutofillIssueReport(diagnostics, [], doc, [], 12);

    expect(report.issueCount).toBe(2);
    expect(report.skippedFields.map((field) => field.label)).toEqual([
      'How did you hear about us?',
      'LinkedIn URL',
    ]);
    expect(report.skippedFields[0]?.reason).toContain('Unidentified');
    expect(report.summary).toContain('1 unidentified');
    expect(report.summary).toContain('1 unfilled');
  });

  it('merges thrown fill errors into skipped fields', () => {
    const report = buildAutofillIssueReport(
      [],
      [],
      doc,
      [{ label: 'Phone', error: 'Option not found', fieldId: 'f1' }],
      3
    );

    expect(report.issueCount).toBe(1);
    expect(report.skippedFields[0]?.category).toBe('error');
    expect(report.skippedFields[0]?.reason).toContain('Option not found');
  });
});

describe('formatIssueSummary', () => {
  it('builds a readable summary line', () => {
    expect(
      formatIssueSummary(
        { unrecognized: 2, still_empty: 1, missing_profile_value: 1 },
        4
      )
    ).toBe('2 unidentified · 1 unfilled · 1 missing profile');
  });
});
