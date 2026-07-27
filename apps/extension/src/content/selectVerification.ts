import { isPlaceholderSelectOption } from '../shared/usStates';
import { matchesCustomOption, scoreSelectOptionMatch } from './autofillEngine.matching';

function resolveSearchComboboxInput(element: HTMLElement): HTMLInputElement | null {
  if (element.tagName === 'INPUT') {
    const input = element as HTMLInputElement;
    if (
      input.getAttribute('role') === 'combobox' ||
      input.getAttribute('data-input') === 'select-search-input' ||
      input.classList.contains('select__input')
    ) {
      return input;
    }
  }
  return element.querySelector(
    'input[role="combobox"], input[data-input="select-search-input"], input.select__input'
  ) as HTMLInputElement | null;
}

function resolveComboboxRoot(element: HTMLElement): HTMLElement {
  return (
    (element.closest('.select-shell') as HTMLElement | null) ||
    (element.closest('[role="combobox"]') as HTMLElement | null) ||
    element
  );
}

function comboboxDisplayText(root: HTMLElement): string {
  const reactSelectValue = root.querySelector('.select__single-value, [class*="single-value"]');
  const reactSelectText = reactSelectValue?.textContent?.replace(/\s+/g, ' ').trim() || '';
  if (reactSelectText && !isGenericComboboxLabel(reactSelectText)) {
    return reactSelectText;
  }

  const placeholder = root.querySelector('.select__placeholder, [class*="placeholder"]');
  if (placeholder && !reactSelectValue) {
    return '';
  }

  const selectedChip = root.querySelector(
    '[class*="singleValue"], [class*="single-value"], [class*="multiValue"], [data-selected], [class*="value-container"] [class*="value"]'
  );
  const chipText = selectedChip?.textContent?.replace(/\s+/g, ' ').trim() || '';
  if (chipText && !/^(select\.\.\.|select|search|textbox|choose)$/i.test(chipText)) {
    return chipText;
  }

  const button = root.querySelector('button[aria-haspopup], [role="button"][aria-haspopup]');
  const buttonText = button?.textContent?.replace(/\s+/g, ' ').trim() || '';
  if (buttonText && !/^(select\.\.\.|select|search|textbox|choose)$/i.test(buttonText)) {
    return buttonText;
  }

  const child = root.querySelector('p, span[class*="value"]');
  const childText = child?.textContent?.replace(/\s+/g, ' ').trim() || '';
  if (childText && !/^(select\.\.\.|select|search|textbox|choose)$/i.test(childText)) {
    return childText;
  }

  return '';
}

function isGenericComboboxLabel(text: string): boolean {
  return /^(select\.\.\.|select|search|textbox|choose)$/i.test(text.trim());
}

function displayMatchesExpected(display: string, expectedValue?: string): boolean {
  if (!display) return false;
  if (!expectedValue?.trim()) return true;
  return (
    matchesCustomOption(display, expectedValue) ||
    scoreSelectOptionMatch(display, expectedValue) >= 75
  );
}

/** True when a dropdown has a committed option — not just typed text in a search box. */
export function isSelectOptionCommitted(element: HTMLElement, expectedValue?: string): boolean {
  if (element.tagName === 'SELECT') {
    const select = element as HTMLSelectElement;
    const opt = select.options[select.selectedIndex];
    const text = opt?.text?.trim() || '';
    if (!text || isPlaceholderSelectOption(text, opt?.value)) return false;
    return displayMatchesExpected(text, expectedValue);
  }

  const root = resolveComboboxRoot(element);
  const display = comboboxDisplayText(root);
  if (displayMatchesExpected(display, expectedValue)) return true;

  const input = resolveSearchComboboxInput(root);
  if (input?.value?.trim()) {
    // Raw input text alone is not a committed selection on searchable dropdowns.
    return false;
  }

  return false;
}

export function readCommittedSelectValue(element: HTMLElement): string {
  if (element.tagName === 'SELECT') {
    const select = element as HTMLSelectElement;
    const opt = select.options[select.selectedIndex];
    const text = opt?.text?.trim() || '';
    return isPlaceholderSelectOption(text, opt?.value) ? '' : text;
  }

  const root = resolveComboboxRoot(element);
  return comboboxDisplayText(root);
}
