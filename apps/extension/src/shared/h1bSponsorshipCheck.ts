/** FrogHire-inspired local H1B / visa sponsorship signal detection from job text. */

export type H1bSponsorshipStatus = 'likely' | 'unlikely' | 'unknown';

export interface H1bSponsorshipResult {
  status: H1bSponsorshipStatus;
  label: string;
  reason: string;
  signals: string[];
}

const LIKELY_PATTERNS: Array<{ pattern: RegExp; signal: string }> = [
  { pattern: /\bh-?1b\b/i, signal: 'H-1B mentioned' },
  { pattern: /\bvisa sponsorship\b/i, signal: 'Visa sponsorship' },
  { pattern: /\bwill sponsor\b/i, signal: 'Will sponsor' },
  { pattern: /\bsponsorship (?:is )?available\b/i, signal: 'Sponsorship available' },
  { pattern: /\bopen to (?:visa )?sponsor/i, signal: 'Open to sponsorship' },
  { pattern: /\b(?:opt|cpt)\b/i, signal: 'OPT/CPT friendly' },
  { pattern: /\bemployment-based visa\b/i, signal: 'Employment visa' },
  { pattern: /\bperm\b/i, signal: 'PERM mentioned' },
  { pattern: /\be-?verify\b/i, signal: 'E-Verify' }
];

const UNLIKELY_PATTERNS: Array<{ pattern: RegExp; signal: string }> = [
  { pattern: /\bno (?:visa )?sponsorship\b/i, signal: 'No sponsorship stated' },
  { pattern: /\bunable to sponsor\b/i, signal: 'Unable to sponsor' },
  { pattern: /\bnot (?:able to )?sponsor\b/i, signal: 'Will not sponsor' },
  { pattern: /\bwithout sponsorship\b/i, signal: 'Without sponsorship' },
  { pattern: /\bdo not sponsor\b/i, signal: 'Do not sponsor' },
  { pattern: /\bdoes not sponsor\b/i, signal: 'Does not sponsor' },
  { pattern: /\bnot provide sponsorship\b/i, signal: 'No sponsorship provided' },
  { pattern: /\b(?:us|u\.s\.?) citizens? only\b/i, signal: 'US citizens only' },
  { pattern: /\bmust be (?:a )?(?:us|u\.s\.?) (?:citizen|permanent resident)\b/i, signal: 'Citizens/PR only' },
  { pattern: /\bauthorized to work (?:in the )?(?:us|u\.s\.?) without sponsorship\b/i, signal: 'No sponsorship required' },
  { pattern: /\bno immigration sponsorship\b/i, signal: 'No immigration sponsorship' }
];

export function checkH1bSponsorship(text: string): H1bSponsorshipResult {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (!normalized) {
    return {
      status: 'unknown',
      label: 'H1B unknown',
      reason: 'No job description to analyze.',
      signals: []
    };
  }

  const likely: string[] = [];
  const unlikely: string[] = [];

  for (const { pattern, signal } of LIKELY_PATTERNS) {
    if (pattern.test(normalized)) likely.push(signal);
  }
  for (const { pattern, signal } of UNLIKELY_PATTERNS) {
    if (pattern.test(normalized)) unlikely.push(signal);
  }

  if (unlikely.length > 0) {
    return {
      status: 'unlikely',
      label: 'Unlikely H1B',
      reason: unlikely[0],
      signals: unlikely.slice(0, 4)
    };
  }

  if (likely.length > 0) {
    return {
      status: 'likely',
      label: 'H1B friendly',
      reason: likely[0],
      signals: likely.slice(0, 4)
    };
  }

  return {
    status: 'unknown',
    label: 'H1B unclear',
    reason: 'No explicit sponsorship language found.',
    signals: []
  };
}

export function h1bStatusColor(status: H1bSponsorshipStatus): string {
  switch (status) {
    case 'likely':
      return '#4ade80';
    case 'unlikely':
      return '#f87171';
    default:
      return '#94a3b8';
  }
}
