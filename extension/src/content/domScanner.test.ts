import { describe, expect, it } from 'vitest';
import { getLabelText } from './domScanner';

describe('getLabelText react-select labels', () => {
  it('ignores placeholder ids in multi-value aria-labelledby', () => {
    const doc = {
      getElementById: (id: string) => {
        if (id === 'clearance-label') {
          return { textContent: 'CLEARANCE ELIGIBILITY - security clearance required' };
        }
        if (id === 'react-select-clearance-placeholder') {
          return { textContent: 'Select...' };
        }
        return null;
      },
      querySelector: () => null,
    } as unknown as Document;

    const input = {
      tagName: 'INPUT',
      id: '',
      parentElement: null,
      getAttribute: (name: string) => {
        if (name === 'role') return 'combobox';
        if (name === 'aria-labelledby') return 'clearance-label react-select-clearance-placeholder';
        return null;
      },
      closest: () => null,
    } as unknown as HTMLElement;

    expect(getLabelText(input, doc)).toContain('CLEARANCE ELIGIBILITY');
  });
});
