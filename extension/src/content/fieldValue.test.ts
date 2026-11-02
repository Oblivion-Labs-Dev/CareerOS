import { describe, expect, it } from 'vitest';
import { parseLocationParts } from '../shared/usStates';

describe('parseLocationParts zip', () => {
  it('extracts trailing zip from location string', () => {
    expect(parseLocationParts('Auburn, WA 98092')).toEqual({
      city: 'Auburn',
      state: 'WA',
      zip: '98092'
    });
  });

  it('keeps city/state when no zip is present', () => {
    expect(parseLocationParts('Seattle, WA')).toEqual({
      city: 'Seattle',
      state: 'WA',
      zip: ''
    });
  });
});
