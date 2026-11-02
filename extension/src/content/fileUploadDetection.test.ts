import { describe, expect, it } from 'vitest';
import {
  detectUploadKindFromHint,
  zoneTextIndicatesKind,
} from './fileUploadDetection';

describe('detectUploadKindFromHint', () => {
  it('prefers cover letter when both hints appear', () => {
    expect(detectUploadKindFromHint('Cover letter — attach your resume notes')).toBe('coverLetter');
  });

  it('detects resume uploads', () => {
    expect(detectUploadKindFromHint('Resume / CV')).toBe('resume');
    expect(detectUploadKindFromHint('Drop or select Resume/CV')).toBe('resume');
  });

  it('detects cover letter uploads', () => {
    expect(detectUploadKindFromHint('Cover letter (optional)')).toBe('coverLetter');
  });

  it('returns null for generic upload zones', () => {
    expect(detectUploadKindFromHint('Drop or select a file (.pdf, .docx)')).toBeNull();
  });
});

describe('zoneTextIndicatesKind', () => {
  it('matches resume drop zones only when resume is mentioned', () => {
    expect(zoneTextIndicatesKind('Drop or select Resume/CV', 'resume')).toBe(true);
    expect(zoneTextIndicatesKind('Drop or select Cover Letter', 'resume')).toBe(false);
  });

  it('matches cover letter drop zones', () => {
    expect(zoneTextIndicatesKind('Drop or select Cover Letter', 'coverLetter')).toBe(true);
    expect(zoneTextIndicatesKind('Drop or select Resume/CV', 'coverLetter')).toBe(false);
  });
});
