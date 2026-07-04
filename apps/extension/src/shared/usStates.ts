/** US state/territory abbreviations → full names (Workday-style dropdowns). */
export const US_STATE_ABBREV_TO_NAME: Record<string, string> = {
  AL: 'Alabama',
  AK: 'Alaska',
  AZ: 'Arizona',
  AR: 'Arkansas',
  CA: 'California',
  CO: 'Colorado',
  CT: 'Connecticut',
  DE: 'Delaware',
  DC: 'District of Columbia',
  FL: 'Florida',
  GA: 'Georgia',
  HI: 'Hawaii',
  ID: 'Idaho',
  IL: 'Illinois',
  IN: 'Indiana',
  IA: 'Iowa',
  KS: 'Kansas',
  KY: 'Kentucky',
  LA: 'Louisiana',
  ME: 'Maine',
  MD: 'Maryland',
  MA: 'Massachusetts',
  MI: 'Michigan',
  MN: 'Minnesota',
  MS: 'Mississippi',
  MO: 'Missouri',
  MT: 'Montana',
  NE: 'Nebraska',
  NV: 'Nevada',
  NH: 'New Hampshire',
  NJ: 'New Jersey',
  NM: 'New Mexico',
  NY: 'New York',
  NC: 'North Carolina',
  ND: 'North Dakota',
  OH: 'Ohio',
  OK: 'Oklahoma',
  OR: 'Oregon',
  PA: 'Pennsylvania',
  RI: 'Rhode Island',
  SC: 'South Carolina',
  SD: 'South Dakota',
  TN: 'Tennessee',
  TX: 'Texas',
  UT: 'Utah',
  VT: 'Vermont',
  VA: 'Virginia',
  WA: 'Washington',
  WV: 'West Virginia',
  WI: 'Wisconsin',
  WY: 'Wyoming',
  AS: 'American Samoa',
  GU: 'Guam',
  MP: 'Northern Mariana Islands',
  PR: 'Puerto Rico',
  VI: 'Virgin Islands'
};

const PLACEHOLDER_SELECT_RE =
  /^(select\s*one|select\.\.\.|select(\s|$)|--|none|choose(\s*one)?|please\s*select)$/i;

export function isPlaceholderSelectOption(text: string, value?: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return true;
  if (PLACEHOLDER_SELECT_RE.test(trimmed)) return true;
  if (value !== undefined && (value === '' || value === '0' || value === '-1')) return true;
  return false;
}

export function getStateMatchVariants(value: string): string[] {
  const trimmed = value.trim().replace(/\./g, '');
  if (!trimmed) return [];

  const variants = new Set<string>([trimmed]);
  const upper = trimmed.toUpperCase();

  if (US_STATE_ABBREV_TO_NAME[upper]) {
    variants.add(upper);
    variants.add(US_STATE_ABBREV_TO_NAME[upper]);
  }

  const byName = Object.entries(US_STATE_ABBREV_TO_NAME).find(
    ([, name]) => name.toLowerCase() === trimmed.toLowerCase()
  );
  if (byName) {
    variants.add(byName[0]);
    variants.add(byName[1]);
  }

  return [...variants];
}

export function matchesStateOption(optionText: string, value: string): boolean {
  const optVariants = getStateMatchVariants(optionText);
  const valVariants = getStateMatchVariants(value);
  for (const option of optVariants) {
    for (const candidate of valVariants) {
      if (option.toLowerCase() === candidate.toLowerCase()) return true;
    }
  }
  return false;
}

/** Prefer full state name for ATS dropdowns (e.g. WA → Washington). */
export function preferredStateFillValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  const upper = trimmed.toUpperCase();
  if (US_STATE_ABBREV_TO_NAME[upper]) return US_STATE_ABBREV_TO_NAME[upper];
  return trimmed;
}

export function parseLocationParts(location: string): { city: string; state: string } {
  const trimmed = location?.trim() || '';
  if (!trimmed) return { city: '', state: '' };

  const commaParts = trimmed.split(',').map((p) => p.trim()).filter(Boolean);
  if (commaParts.length >= 2) {
    return {
      city: commaParts[0],
      state: commaParts[commaParts.length - 1]
    };
  }

  const tokens = trimmed.split(/\s+/);
  if (tokens.length >= 2 && /^[A-Za-z]{2}$/.test(tokens[tokens.length - 1])) {
    return {
      city: tokens.slice(0, -1).join(' '),
      state: tokens[tokens.length - 1]
    };
  }

  return { city: trimmed, state: '' };
}

/** City name for searchable location comboboxes (type "Seattle", pick full option). */
export function resolveLocationCity(location: string): string {
  const { city } = parseLocationParts(location);
  return city || location.trim();
}

export function matchesLocationOption(optionText: string, locationValue: string): boolean {
  const text = optionText.trim().toLowerCase();
  if (!text || !locationValue?.trim()) return false;

  const { city, state } = parseLocationParts(locationValue);
  const cityLower = city.toLowerCase();
  if (!cityLower) return false;

  // Prefer "Seattle, ..." over "Settle, ..."
  if (!text.startsWith(`${cityLower},`) && !text.startsWith(`${cityLower} `)) {
    return false;
  }

  if (!state) return true;

  const stateVariants = getStateMatchVariants(state).map((part) => part.toLowerCase());
  return stateVariants.some((part) => part.length >= 2 && text.includes(part));
}

export function scoreLocationOption(optionText: string, locationValue: string): number {
  if (!matchesLocationOption(optionText, locationValue)) return 0;

  const text = optionText.trim().toLowerCase();
  const { city } = parseLocationParts(locationValue);
  let score = 20;

  if (city && text.startsWith(`${city.toLowerCase()},`)) score += 40;
  if (/united states|, usa\b|, us\b/.test(text)) score += 25;
  if (/washington/.test(text) && /wa\b|washington/.test(locationValue.toLowerCase())) score += 15;

  return score;
}
