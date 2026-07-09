import { describe, expect, it } from 'vitest';
import { isOptionalAddressField, isAddressRelatedField } from './fieldRequired';

describe('fieldRequired', () => {
  it('treats address line 2 as optional', () => {
    expect(isOptionalAddressField('Address Line 2')).toBe(true);
    expect(isOptionalAddressField('Address')).toBe(false);
    expect(isOptionalAddressField('Suite 200')).toBe(true);
  });

  it('detects address-related labels', () => {
    expect(isAddressRelatedField('Postal Code/Zip *')).toBe(true);
    expect(isAddressRelatedField('Country/region of residence *')).toBe(true);
    expect(isAddressRelatedField('Address *')).toBe(true);
    expect(isAddressRelatedField('Email address')).toBe(false);
  });
});
