import { describe, expect, it } from 'vitest';
import { isSelectOptionCommitted, readCommittedSelectValue } from './selectVerification';

describe('isSelectOptionCommitted', () => {
  it('returns false for placeholder native selects', () => {
    const select = {
      tagName: 'SELECT',
      options: [{ text: 'Choose', value: '' }, { text: 'Yes', value: 'yes' }],
      selectedIndex: 0,
    } as unknown as HTMLSelectElement;
    expect(isSelectOptionCommitted(select)).toBe(false);
  });

  it('returns true for a selected native option', () => {
    const select = {
      tagName: 'SELECT',
      options: [{ text: 'Choose', value: '' }, { text: 'Yes', value: 'yes' }],
      selectedIndex: 1,
    } as unknown as HTMLSelectElement;
    expect(isSelectOptionCommitted(select, 'Yes')).toBe(true);
    expect(readCommittedSelectValue(select)).toBe('Yes');
  });

  it('returns false when only search text exists in a combobox input', () => {
    const input = {
      tagName: 'INPUT',
      value: 'Male',
      getAttribute: () => 'combobox',
      closest: () => root,
    } as unknown as HTMLInputElement;
    const root = {
      tagName: 'DIV',
      getAttribute: () => 'combobox',
      closest: () => root,
      querySelector: () => input,
      textContent: '',
    } as unknown as HTMLElement;

    expect(isSelectOptionCommitted(root, 'Male')).toBe(false);
  });

  it('returns true when react-select shows a committed single value', () => {
    const shell = {
      tagName: 'DIV',
      classList: { contains: () => true },
      closest: (selector: string) => (selector === '.select-shell' ? shell : null),
      querySelector: (selector: string) => {
        if (selector.includes('single-value')) {
          return { textContent: 'Yes' };
        }
        if (selector.includes('placeholder')) {
          return null;
        }
        return null;
      },
      textContent: '',
    } as unknown as HTMLElement;
    const input = {
      tagName: 'INPUT',
      classList: { contains: (c: string) => c === 'select__input' },
      getAttribute: (name: string) => (name === 'role' ? 'combobox' : null),
      closest: (selector: string) => (selector === '.select-shell' ? shell : selector === '[role="combobox"]' ? input : null),
      value: '',
    } as unknown as HTMLInputElement;

    expect(isSelectOptionCommitted(input, 'Yes')).toBe(true);
    expect(readCommittedSelectValue(input)).toBe('Yes');
  });

  it('returns false when only surrounding question copy exists (Greenhouse screening)', () => {
    const shell = {
      tagName: 'DIV',
      classList: { contains: () => true },
      closest: (selector: string) => (selector === '.select-shell' ? shell : null),
      querySelector: (selector: string) => {
        if (selector.includes('single-value') || selector.includes('placeholder')) return null;
        if (selector.includes('select__input')) return input;
        return null;
      },
      textContent:
        'CLEARANCE ELIGIBILITY - security clearance required. Do you presently hold an active clearance? Select...',
    } as unknown as HTMLElement;
    const input = {
      tagName: 'INPUT',
      classList: { contains: (c: string) => c === 'select__input' },
      getAttribute: (name: string) => (name === 'role' ? 'combobox' : null),
      closest: (selector: string) =>
        selector === '.select-shell' ? shell : selector === '[role="combobox"]' ? input : null,
      value: '',
    } as unknown as HTMLInputElement;

    expect(isSelectOptionCommitted(input)).toBe(false);
    expect(isSelectOptionCommitted(input, 'No')).toBe(false);
  });
});
