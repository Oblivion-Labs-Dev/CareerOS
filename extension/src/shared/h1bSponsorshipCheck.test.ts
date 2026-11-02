import { describe, expect, it } from 'vitest';
import { checkH1bSponsorship } from './h1bSponsorshipCheck';

describe('checkH1bSponsorship', () => {
  it('detects likely sponsorship from job text', () => {
    const result = checkH1bSponsorship(
      'We offer visa sponsorship and welcome H-1B candidates with OPT experience.'
    );
    expect(result.status).toBe('likely');
    expect(result.signals.length).toBeGreaterThan(0);
  });

  it('detects unlikely sponsorship from job text', () => {
    const result = checkH1bSponsorship(
      'Must be authorized to work in the US without sponsorship. No visa sponsorship available.'
    );
    expect(result.status).toBe('unlikely');
  });

  it("detects unlikely sponsorship from 'can't offer visa sponsorship'", () => {
    const result = checkH1bSponsorship(
      "Will you require visa sponsorship now or in the future? Please note we can't offer visa sponsorship for this role."
    );
    expect(result.status).toBe('unlikely');
    expect(result.signals[0]).toBe('Cannot offer sponsorship');
  });

  it('returns unknown when no signals found', () => {
    const result = checkH1bSponsorship('Great role for a software engineer in San Francisco.');
    expect(result.status).toBe('unknown');
  });
});
