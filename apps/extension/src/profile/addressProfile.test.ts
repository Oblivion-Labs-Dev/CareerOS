import { describe, expect, it } from 'vitest';
import { addressValueForKey, mergeAddressIntoProfile } from '../profile/addressProfile';
import { createEmptyProfile } from '../profile/profileStore';

describe('addressProfile', () => {
  it('returns saved address parts from custom fields', () => {
    const profile = createEmptyProfile();
    profile.customFields = {
      addressLine1: '13310 SE 306th St',
      city: 'Auburn',
      state: 'Washington',
      zip: '98092',
      country: 'United States'
    };

    expect(addressValueForKey('address', profile)).toBe('13310 SE 306th St');
    expect(addressValueForKey('city', profile)).toBe('Auburn');
    expect(addressValueForKey('state', profile)).toBe('Washington');
    expect(addressValueForKey('zip', profile)).toBe('98092');
    expect(addressValueForKey('country', profile)).toBe('United States');
  });

  it('builds a location string from captured address parts', () => {
    const profile = createEmptyProfile();
    const merged = mergeAddressIntoProfile(profile, {
      city: 'Auburn',
      state: 'WA',
      zip: '98092'
    });

    expect(merged.location).toBe('Auburn, WA 98092');
  });
});
