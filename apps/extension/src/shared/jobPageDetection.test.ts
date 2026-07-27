import { describe, expect, it } from 'vitest';
import {
  isGreenhouseSubmissionSuccess,
  isSubmissionConfirmationUrl,
  isSubmissionSuccessPage
} from './jobPageDetection';

describe('jobPageDetection submit confirmation', () => {
  it('detects Greenhouse confirmation URLs', () => {
    expect(
      isSubmissionConfirmationUrl('https://job-boards.greenhouse.io/okta/jobs/7599857/confirmation')
    ).toBe(true);
  });

  it('detects in-page Greenhouse thank-you without URL change', () => {
    const doc = {
      location: { href: 'https://job-boards.greenhouse.io/okta/jobs/7599857' },
      body: {
        innerText: 'Thank you for applying to Okta. We have received your application.'
      },
      querySelector: () => null,
      querySelectorAll: () => ({ length: 2 })
    } as unknown as Document;

    expect(isGreenhouseSubmissionSuccess(doc)).toBe(true);
    expect(isSubmissionSuccessPage(doc)).toBe(true);
  });

  it('does not treat active application forms as submitted', () => {
    const doc = {
      location: { href: 'https://job-boards.greenhouse.io/okta/jobs/7599857' },
      body: {
        innerText: 'Senior Software Engineer, AI — apply now'
      },
      querySelector: () => null,
      querySelectorAll: () => ({ length: 35 })
    } as unknown as Document;

    expect(isGreenhouseSubmissionSuccess(doc)).toBe(false);
  });
});
