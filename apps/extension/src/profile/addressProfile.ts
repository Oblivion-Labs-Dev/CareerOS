import { UserProfile } from '../shared/types';
import { parseLocationParts, preferredStateFillValue } from '../shared/usStates';
import { scanPage, ScannedField } from '../content/domScanner';
import { resolveFieldLabel } from '../content/fieldInference';
import { readFieldDisplayValue } from '../content/fieldValue';
import { isOptionalAddressField } from '../content/fieldRequired';
import { saveProfile } from './profileStore';

function normalizeLabel(label: string): string {
  return label.replace(/\*+$/, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function mapAddressValue(field: ScannedField, label: string, value: string, customFields: Record<string, string>): void {
  const normalized = normalizeLabel(label);

  if (isOptionalAddressField(label)) return;

  if (
    normalized === 'address' ||
    (/address/i.test(label) && !/line\s*2|line\s*two/i.test(label) && !/country|region/.test(label))
  ) {
    customFields.addressLine1 = value;
    customFields.street = value;
    return;
  }

  if (/\bcity\b/.test(normalized)) {
    customFields.city = value;
    return;
  }

  if (/\bstate\b|province/.test(normalized)) {
    customFields.state = value;
    return;
  }

  if (/zip|postal|postcode/.test(normalized)) {
    customFields.zip = value;
    customFields.postalCode = value;
    return;
  }

  if (/country|region of residence/.test(normalized)) {
    customFields.country = value;
  }
}

export function mergeAddressIntoProfile(profile: UserProfile, customFields: Record<string, string>): UserProfile {
  const nextCustomFields = {
    ...(profile.customFields || {}),
    ...customFields
  };

  const { city: locationCity, state: locationState, zip: locationZip } = parseLocationParts(profile.location || '');
  const city = nextCustomFields.city || locationCity;
  const state = nextCustomFields.state || locationState;
  const zip = nextCustomFields.zip || nextCustomFields.postalCode || locationZip;

  let location = profile.location?.trim() || '';
  if (city && state) {
    location = zip ? `${city}, ${state} ${zip}` : `${city}, ${state}`;
  }

  return {
    ...profile,
    location,
    customFields: nextCustomFields
  };
}

export async function captureAddressFromPage(
  doc: Document,
  profile: UserProfile,
  persist = true
): Promise<UserProfile> {
  const fields = scanPage(doc);
  const captured: Record<string, string> = {};

  for (const field of fields) {
    const label = resolveFieldLabel(field, doc) || field.labelText || '';
    if (!isAddressRelatedLabel(label)) continue;

    const value = readFieldDisplayValue(field, doc);
    if (!value) continue;

    mapAddressValue(field, label, value, captured);
  }

  if (!Object.keys(captured).length) {
    return profile;
  }

  const next = mergeAddressIntoProfile(profile, captured);
  if (persist) {
    await saveProfile(next);
  }
  return next;
}

function isAddressRelatedLabel(label: string): boolean {
  return /address|street|city|state|province|zip|postal|postcode|country|region of residence|residence/i.test(
    normalizeLabel(label)
  );
}

export function addressValueForKey(key: string, profile: UserProfile): string {
  const { city, state, zip } = parseLocationParts(profile.location || '');
  const custom = profile.customFields || {};

  switch (key) {
    case 'address':
      return custom.addressLine1 || custom.street || '';
    case 'city':
      return custom.city || city;
    case 'state':
      return preferredStateFillValue(custom.state || state);
    case 'zip':
      return custom.zip || custom.postalCode || zip;
    case 'country':
      return custom.country || 'United States';
    default:
      return '';
  }
}
