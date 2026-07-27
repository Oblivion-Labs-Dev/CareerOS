import { ScannedField, getLabelText } from './domScanner';
import { FileAttachment } from '../shared/types';
import { isSynonymMatch, matchesCustomOption, matchesRadioOption, pickBestMatchingOptionText, scoreSelectOptionMatch, expandSelectFillValues } from './autofillEngine.matching';
import {
  isPlaceholderSelectOption,
  matchesStateOption,
  matchesLocationOption,
  scoreLocationOption,
  resolveLocationCity
} from '../shared/usStates';
import { logToServer } from '../shared/serverLog';
import { detectFileInputUploadKind, detectUploadKindFromHint } from './fileUploadDetection';
import { isSelectOptionCommitted } from './selectVerification';
import { fillReactSelectInMainWorld } from './mainWorldBridge';

/**
 * Bypasses virtual DOM frameworks (React, Angular, Vue) by calling the native setter.
 */
function setNativeValue(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  let prototypeValueSetter;

  // Try direct prototype first
  const prototype = Object.getPrototypeOf(element);
  prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;

  // Fallback to standard HTML prototypes if needed (e.g. customized prototype chains)
  if (!prototypeValueSetter) {
    const standardProto = element.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    prototypeValueSetter = Object.getOwnPropertyDescriptor(standardProto, 'value')?.set;
  }

  if (prototypeValueSetter) {
    prototypeValueSetter.call(element, value);
  } else {
    element.value = value;
  }
}

/**
 * Searches for a visible autocomplete suggestion near a combobox input.
 */
function pickBestListboxOption(
  candidates: HTMLElement[],
  value: string,
  locationContext?: string
): HTMLElement | undefined {
  const locationValue = locationContext || value;
  let best: { el: HTMLElement; score: number } | null = null;

  for (const el of candidates) {
    const text = el.textContent?.trim() || '';
    if (!text) continue;

    let score = 0;
    if (matchesLocationOption(text, locationValue)) {
      score = scoreLocationOption(text, locationValue);
    } else {
      score = scoreSelectOptionMatch(text, value);
    }

    if (score > 0 && (!best || score > best.score)) {
      best = { el, score };
    }
  }

  return best?.el;
}

function focusWithoutScroll(element: HTMLElement): void {
  try {
    element.focus({ preventScroll: true });
  } catch {
    element.focus();
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Run a function in the page's main JS world so clicks are trusted (required by React Select / Greenhouse). */
function runInMainWorld<T>(fn: (...args: unknown[]) => T, ...args: unknown[]): T | undefined {
  const marker = `__careeros_main_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const payload = JSON.stringify(args);
  const script = document.createElement('script');
  script.textContent = `(function(){
    try {
      var fn = ${fn.toString()};
      var result = fn.apply(null, ${payload});
      document.documentElement.setAttribute(${JSON.stringify(marker)}, JSON.stringify(result));
    } catch (e) {
      document.documentElement.setAttribute(${JSON.stringify(marker)}, JSON.stringify({ __error: String(e) }));
    }
  })();`;
  (document.documentElement || document.head).appendChild(script);
  script.remove();
  const raw = document.documentElement.getAttribute(marker);
  document.documentElement.removeAttribute(marker);
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw) as { __error?: string } & T;
    if (parsed && typeof parsed === 'object' && '__error' in parsed) return undefined;
    return parsed as T;
  } catch {
    return undefined;
  }
}

function mainWorldOpenReactSelect(inputId: string): boolean {
  return (
    runInMainWorld(
      (id: unknown) => {
        const input = document.getElementById(String(id)) as HTMLInputElement | null;
        if (!input) return false;
        const shell = input.closest('.select-shell');
        const control = shell?.querySelector('.select__control') as HTMLElement | null;
        input.focus();
        control?.click();
        input.click();
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
        return input.getAttribute('aria-expanded') === 'true';
      },
      inputId
    ) ?? false
  );
}

function mainWorldClickSelectOption(optionText: string): boolean {
  return (
    runInMainWorld((text: unknown) => {
      const target = String(text).toLowerCase().trim();
      const options = Array.from(
        document.querySelectorAll('[role="option"], .select__option, [class*="select__option"]')
      ) as HTMLElement[];
      for (const option of options) {
        const label = (option.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
        if (!label || label === 'select...') continue;
        if (label === target || label.includes(target) || target.includes(label)) {
          option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
          option.click();
          return true;
        }
      }
      return false;
    }, optionText) ?? false
  );
}

async function fillReactSelectViaMainWorld(input: HTMLInputElement, value: string): Promise<boolean> {
  if (isSelectOptionCommitted(input, value)) return true;
  if (!input.id) {
    input.id = `careeros-combobox-${Math.random().toString(36).slice(2, 9)}`;
  }

  closeOpenListboxes();
  clearComboboxSearchText(input);
  input.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' as ScrollBehavior });

  if (await fillReactSelectInMainWorld(input.id, value)) {
    await sleep(80);
    if (isSelectOptionCommitted(input, value)) return true;
  }

  // Legacy inline injection fallback when background scripting is unavailable.
  const clickTexts = expandSelectFillValues(value).flatMap((candidate) => {
    const best = pickBestMatchingOptionText(
      collectComboboxOptions(input, true).map((el) => el.textContent?.replace(/\s+/g, ' ').trim() || ''),
      candidate
    );
    return [best, candidate].filter(Boolean) as string[];
  });

  for (let attempt = 0; attempt < 3; attempt++) {
    mainWorldOpenReactSelect(input.id);
    await sleep(180);
    for (const text of clickTexts) {
      if (mainWorldClickSelectOption(text)) {
        await sleep(150);
        if (isSelectOptionCommitted(input, value)) return true;
      }
    }
    if (/^(yes|no)$/i.test(value.trim()) && (await tryKeyboardSelectOption(input, value))) return true;
    await sleep(120);
  }

  return false;
}

function simulateUserClick(target: HTMLElement): void {
  const rect = target.getBoundingClientRect();
  const clientX = rect.left + Math.max(1, rect.width / 2);
  const clientY = rect.top + Math.max(1, rect.height / 2);
  const pointerInit: PointerEventInit = {
    bubbles: true,
    cancelable: true,
    view: document.defaultView || window,
    clientX,
    clientY,
    pointerId: 1,
    pointerType: 'mouse',
    isPrimary: true,
    button: 0,
    buttons: 1
  };
  const mouseInit: MouseEventInit = {
    bubbles: true,
    cancelable: true,
    view: document.defaultView || window,
    clientX,
    clientY,
    button: 0,
    buttons: 1
  };

  target.dispatchEvent(new PointerEvent('pointerdown', pointerInit));
  target.dispatchEvent(new MouseEvent('mousedown', mouseInit));
  target.dispatchEvent(new PointerEvent('pointerup', pointerInit));
  target.dispatchEvent(new MouseEvent('mouseup', mouseInit));
  if (typeof target.click === 'function') {
    target.click();
  }
}

function clickListboxOption(matchedElement: HTMLElement, input: HTMLInputElement): void {
  console.log(`[JobFill] Selecting listbox option: "${matchedElement.textContent?.trim()}"`);
  matchedElement.dispatchEvent(
    new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0, buttons: 1, view: window })
  );
  simulateUserClick(matchedElement);
  matchedElement.dispatchEvent(new Event('change', { bubbles: true }));
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

async function tryTypeToSelectOption(input: HTMLInputElement, value: string): Promise<boolean> {
  const trimmed = value.trim();
  if (!trimmed) return false;

  closeOpenListboxes();
  clearComboboxSearchText(input);
  focusWithoutScroll(input);
  simulateUserClick(input);
  await sleep(120);

  const prefix = trimmed.slice(0, Math.min(15, trimmed.length));
  dispatchReactInput(input, prefix);
  input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: prefix }));

  for (const delayMs of [120, 250, 450]) {
    await sleep(delayMs);
    if (await trySelectComboboxOption(input, value)) return true;
  }

  input.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true })
  );
  await sleep(120);
  return isSelectOptionCommitted(input, value);
}

function selectAutocompleteOption(input: HTMLInputElement, value: string, locationContext?: string) {
  const trySelect = (delayMs: number) => {
    setTimeout(() => {
      const listboxId = input.getAttribute('aria-controls') || input.getAttribute('aria-owns');
      const searchRoot = listboxId ? document.getElementById(listboxId) : null;
      const candidates = Array.from(
        (searchRoot || input.parentElement || document).querySelectorAll('[role="option"], li')
      ) as HTMLElement[];

      const matchedElement = pickBestListboxOption(
        candidates.filter((el) => el !== input && !el.contains(input)),
        value,
        locationContext
      );

      if (matchedElement) {
        clickListboxOption(matchedElement, input);
      }
    }, delayMs);
  };

  trySelect(400);
  trySelect(900);
}

function dispatchReactInput(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const tracker = (element as HTMLInputElement & { _valueTracker?: { setValue: (v: string) => void } })._valueTracker;
  if (tracker) {
    tracker.setValue('');
  }

  setNativeValue(element, value);

  element.dispatchEvent(
    new InputEvent('input', {
      bubbles: true,
      cancelable: true,
      inputType: 'insertFromPaste',
      data: value
    })
  );
  element.dispatchEvent(new Event('change', { bubbles: true }));
}

function normalizePhoneForInput(value: string): string {
  const digits = value.replace(/\D/g, '');
  if (digits.length === 11 && digits.startsWith('1')) {
    return digits.slice(1);
  }
  if (digits.length >= 10 && digits.length <= 15 && /[\d+() -]{7,}/.test(value)) {
    return digits.length === 11 && digits.startsWith('1') ? digits.slice(1) : digits;
  }
  return value;
}

/**
 * Fills standard text inputs or textareas
 */
export function fillTextOrTextArea(element: HTMLInputElement | HTMLTextAreaElement, value: string): boolean {
  if (!value.trim()) return false;

  const isLocationCombobox =
    element instanceof HTMLInputElement &&
    (element.getAttribute('role') === 'combobox' ||
      element.getAttribute('aria-autocomplete') === 'list' ||
      /start typing/i.test(element.getAttribute('placeholder') || '') ||
      /location|city|address|residence/i.test(
        `${element.getAttribute('aria-label') || ''} ${element.id} ${element.name}`
      ));

  const usesAutocomplete =
    element instanceof HTMLInputElement &&
    (element.getAttribute('role') === 'combobox' ||
      element.getAttribute('aria-autocomplete') === 'list' ||
      element.getAttribute('data-input') === 'select-search-input' ||
      element.getAttribute('aria-haspopup') === 'listbox' ||
      element.classList.contains('select__input') ||
      Boolean(element.closest('.select-shell')) ||
      /start typing/i.test(element.getAttribute('placeholder') || ''));

  // Searchable dropdowns must pick a list option — typing alone is not valid.
  if (isLocationCombobox || usesAutocomplete) {
    return false;
  }

  const fillValue =
    element instanceof HTMLInputElement &&
    (element.type === 'tel' || /phone|tel|mobile/i.test(element.autocomplete))
      ? normalizePhoneForInput(value)
      : element instanceof HTMLInputElement && /[\d+() -]{7,}/.test(value) && value.replace(/\D/g, '').length >= 10
        ? normalizePhoneForInput(value)
        : value;

  focusWithoutScroll(element);
  dispatchReactInput(element, fillValue);
  return true;
}

function closeOpenListboxes(): void {
  const escape = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true });
  document.activeElement?.dispatchEvent(escape);
  document.dispatchEvent(escape);
}

function isReactSelectInput(input: HTMLInputElement): boolean {
  return input.classList.contains('select__input') || !!input.closest('.select-shell');
}

async function openReactSelectMenu(input: HTMLInputElement): Promise<boolean> {
  const shell = input.closest('.select-shell') as HTMLElement | null;
  const control = shell?.querySelector('.select__control') as HTMLElement | null;
  const toggle = shell?.querySelector('.select__indicators button, button.icon-button') as HTMLElement | null;

  shell?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' as ScrollBehavior });
  focusWithoutScroll(input);
  simulateUserClick(input);

  if (control) {
    simulateUserClick(control);
    control.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 }));
  }
  if (input.getAttribute('aria-expanded') !== 'true' && toggle) {
    simulateUserClick(toggle);
  }
  input.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true, cancelable: true })
  );

  for (let wait = 0; wait < 8; wait++) {
    await sleep(80);
    if (input.getAttribute('aria-expanded') === 'true' || collectComboboxOptions(input).length > 0) {
      return true;
    }
  }
  return false;
}

async function tryKeyboardSelectOption(input: HTMLInputElement, value: string): Promise<boolean> {
  await openReactSelectMenu(input);
  const options = collectComboboxOptions(input, true);
  if (!options.length) return false;

  const targetIndex = options.findIndex((option) => {
    const text = option.textContent?.replace(/\s+/g, ' ').trim() || '';
    return scoreSelectOptionMatch(text, value) >= 75;
  });
  const steps = targetIndex >= 0 ? targetIndex + 1 : 1;

  closeOpenListboxes();
  await openReactSelectMenu(input);
  for (let step = 0; step < steps; step++) {
    input.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true, cancelable: true })
    );
    await sleep(50);
  }
  input.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true })
  );
  await sleep(120);
  return isSelectOptionCommitted(input, value);
}

function clearComboboxSearchText(input: HTMLInputElement): void {
  dispatchReactInput(input, '');
  input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
}

function collectComboboxOptions(input: HTMLInputElement, includeHidden = false): HTMLElement[] {
  const listboxId = input.getAttribute('aria-controls') || input.getAttribute('aria-owns');
  const searchRoots: ParentNode[] = [];
  const shell = input.closest('.select-shell');
  if (shell) {
    const menu = shell.querySelector('.select__menu');
    if (menu) searchRoots.push(menu);
  }
  if (listboxId) {
    const listbox = document.getElementById(listboxId);
    if (listbox) searchRoots.push(listbox);
  }
  searchRoots.push(document);

  const seen = new Set<HTMLElement>();
  const options: HTMLElement[] = [];
  const selectors = [
    '[role="option"]',
    '.select__option',
    '[class*="select__option"]',
    'li[class*="option"]'
  ];

  for (const root of searchRoots) {
    for (const selector of selectors) {
      for (const el of Array.from(root.querySelectorAll(selector)) as HTMLElement[]) {
        if (el === input || el.contains(input) || seen.has(el)) continue;
        seen.add(el);
        options.push(el);
      }
    }
  }

  if (includeHidden) return options;

  return options.filter((el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
}

async function trySelectComboboxOption(
  input: HTMLInputElement,
  value: string,
  locationContext?: string
): Promise<boolean> {
  const candidates = collectComboboxOptions(input);
  const matchedOption = pickBestListboxOption(candidates, value, locationContext);
  if (!matchedOption) return false;
  clickListboxOption(matchedOption, input);
  await sleep(120);
  return isSelectOptionCommitted(input, value);
}

async function fillReactSelectCombobox(
  input: HTMLInputElement,
  value: string,
  locationContext?: string
): Promise<boolean> {
  if (isSelectOptionCommitted(input, value)) return true;

  if (input.closest('.select-shell')) {
    const viaMain = await fillReactSelectViaMainWorld(input, value);
    if (viaMain) return true;
  }

  closeOpenListboxes();
  clearComboboxSearchText(input);

  if (/^(yes|no)$/i.test(value.trim())) {
    if (await tryKeyboardSelectOption(input, value)) return true;
    if (await tryTypeToSelectOption(input, value)) return true;
  }

  if (await tryTypeToSelectOption(input, value)) return true;

  for (let attempt = 0; attempt < 4; attempt++) {
    await openReactSelectMenu(input);
    if (await trySelectComboboxOption(input, value, locationContext)) {
      return true;
    }

    const options = collectComboboxOptions(input);
    for (const option of options) {
      const text = option.textContent?.replace(/\s+/g, ' ').trim() || '';
      if (scoreSelectOptionMatch(text, value) >= 75) {
        simulateUserClick(option);
        await sleep(120);
        if (isSelectOptionCommitted(input, value)) return true;
      }
    }

    if (/^(yes|no)$/i.test(value.trim()) && options.length) {
      if (await tryKeyboardSelectOption(input, value)) return true;
    }

    await sleep(100 * (attempt + 1));
  }

  const typeValue = locationContext ? resolveLocationCity(locationContext) : value;
  const shouldTypeFilter = typeValue.length > 2 && !/^(yes|no)$/i.test(typeValue.trim());
  if (shouldTypeFilter) {
    clearComboboxSearchText(input);
    await openReactSelectMenu(input);
    const searchPrefix = typeValue.split(/\s+/).slice(0, 2).join(' ');
    dispatchReactInput(input, searchPrefix);
    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: searchPrefix }));
    for (const delayMs of [150, 300, 500]) {
      await sleep(delayMs);
      if (await trySelectComboboxOption(input, value, locationContext)) {
        return true;
      }
    }
  }

  clearComboboxSearchText(input);
  closeOpenListboxes();
  return false;
}

async function fillSearchCombobox(element: HTMLInputElement, value: string, locationContext?: string): Promise<boolean> {
  if (isReactSelectInput(element)) {
    return fillReactSelectCombobox(element, value, locationContext);
  }

  const locContext = locationContext || (/,/.test(value) ? value : undefined);
  const typeValue = locContext ? resolveLocationCity(locContext) : value;

  console.log(`[JobFill] Filling search combobox #${element.id} with profile value "${value}"`);
  closeOpenListboxes();
  focusWithoutScroll(element);
  element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));

  if (await trySelectComboboxOption(element, value, locContext)) return true;

  const searchPrefix = typeValue.split(/\s+/).slice(0, 2).join(' ');
  if (searchPrefix) {
    dispatchReactInput(element, searchPrefix);
    element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: searchPrefix }));
  }

  for (const delayMs of [400, 800, 1200, 1600]) {
    await sleep(delayMs);
    if (await trySelectComboboxOption(element, value, locContext)) return true;
  }

  clearComboboxSearchText(element);
  closeOpenListboxes();
  return isSelectOptionCommitted(element, value);
}

function comboboxShowsSelectedOption(element: HTMLElement, value: string, locationContext?: string): boolean {
  const root = (element.closest('[role="combobox"]') as HTMLElement | null) || element;
  const selectedChip = root.querySelector('[class*="multiValue"], [class*="tag"], [data-selected]');
  const parts = [
    selectedChip?.textContent?.replace(/\s+/g, ' ').trim() || '',
    root.querySelector('p, span[class*="value"], [class*="singleValue"]')?.textContent?.replace(/\s+/g, ' ').trim() || ''
  ].filter(Boolean);

  if (!parts.length) return false;

  const locationValue = locationContext || value;
  return parts.some(
    (part) =>
      scoreSelectOptionMatch(part, value) >= 75 ||
      (/,/.test(locationValue) && matchesLocationOption(part, locationValue))
  );
}

function comboboxShowsValue(element: HTMLElement, value: string): boolean {
  return comboboxShowsSelectedOption(element, value);
}

function resolveSearchComboboxInput(element: HTMLElement): HTMLInputElement | null {
  if (element instanceof HTMLInputElement) {
    if (
      element.getAttribute('role') === 'combobox' ||
      element.getAttribute('data-input') === 'select-search-input' ||
      element.classList.contains('select__input')
    ) {
      return element;
    }
  }
  return element.querySelector(
    'input[role="combobox"], input[data-input="select-search-input"], input.select__input'
  ) as HTMLInputElement | null;
}

export async function fillSelect(element: HTMLElement, value: string): Promise<boolean> {
  console.log(`[JobFill] fillSelect called. Element: ${element.tagName}, ID: ${element.id}, Value: ${value}`);
  if (element instanceof HTMLSelectElement) {
    const optionTexts: string[] = [];
    const optionIndexes: number[] = [];

    for (let i = 0; i < element.options.length; i++) {
      const opt = element.options[i];
      if (isPlaceholderSelectOption(opt.text, opt.value)) continue;
      optionTexts.push(opt.text.trim());
      optionIndexes.push(i);
    }

    const bestText = pickBestMatchingOptionText(optionTexts, value);
    if (!bestText) return false;

    const bestIndex = optionIndexes[optionTexts.indexOf(bestText)];
    if (bestIndex === undefined || bestIndex < 0) return false;

    console.log(`[JobFill] Setting native select to option "${bestText}" (index ${bestIndex})`);
    element.selectedIndex = bestIndex;
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.dispatchEvent(new Event('input', { bubbles: true }));
    return isSelectOptionCommitted(element, value);
  } else {
    const searchInput = resolveSearchComboboxInput(element);
    if (searchInput) {
      const locationContext = /,/.test(value) ? value : undefined;
      return fillSearchCombobox(searchInput, value, locationContext);
    }

    // Custom DIV/button combobox filling
    console.log('[JobFill] Triggering mousedown and keyboard open sequence on custom select control and its children');

    closeOpenListboxes();
    await new Promise((r) => setTimeout(r, 50));

    // Focus the elements first to activate framework listeners
    focusWithoutScroll(element);
    
    // Dispatch open events to both the container and the inner text/placeholder child to ensure React handles it
    const openTargets = [element];
    const innerClickable = element.querySelector('p, span, button, div') as HTMLElement;
    if (innerClickable && innerClickable !== element) {
      focusWithoutScroll(innerClickable);
      openTargets.push(innerClickable);
    }

    // Dispatch KeyboardEvents to trigger accessible Radix/Headless dropdowns
    element.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', code: 'Space', bubbles: true }));
    element.dispatchEvent(new KeyboardEvent('keyup', { key: ' ', code: 'Space', bubbles: true }));

    const openTypes = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
    openTargets.forEach((target) => {
      openTypes.forEach((type) => {
        target.dispatchEvent(
          new MouseEvent(type, {
            bubbles: true,
            cancelable: true,
            view: document.defaultView || window,
            button: 0,
            buttons: 1
          })
        );
      });
    });
    
    // Wait for options to render and click the matching item
    return await new Promise<boolean>((resolve) => {
      let retries = 0;
      const maxRetries = 5;

      const checkAndSelect = () => {
        const listboxId = element.getAttribute('aria-controls') || element.getAttribute('aria-owns');
        const hasContainer = listboxId ? !!document.getElementById(listboxId) : true;

        if (listboxId && !hasContainer && retries < maxRetries) {
          retries++;
          console.log(`[JobFill Debug] Listbox container #${listboxId} not mounted yet, retrying... (attempt ${retries})`);
          setTimeout(checkAndSelect, 120);
          return;
        }

        const searchRoot = listboxId ? (document.getElementById(listboxId) || document) : document;
        const candidates = Array.from(
          searchRoot.querySelectorAll('[role="option"], [role="listbox"] [role="option"], li')
        ) as HTMLElement[];
        console.log(`[JobFill Debug] Found ${candidates.length} custom option candidates in scope`);

        const optionTexts = candidates
          .filter((el) => el !== element && !el.contains(element))
          .map((el) => el.textContent?.replace(/\s+/g, ' ').trim() || '')
          .filter(Boolean);
        const bestText = pickBestMatchingOptionText(optionTexts, value);
        const matchedOption = bestText
          ? candidates.find(
              (el) => el.textContent?.replace(/\s+/g, ' ').trim() === bestText && el !== element && !el.contains(element)
            )
          : undefined;

        if (matchedOption) {
          console.log(`[JobFill] Found custom select option match: "${matchedOption.textContent?.trim()}" - simulating click.`);
          const eventTypes = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
          eventTypes.forEach((type) => {
            matchedOption.dispatchEvent(
              new MouseEvent(type, {
                bubbles: true,
                cancelable: true,
                view: document.defaultView || window,
                button: 0,
                buttons: 1
              })
            );
          });
          matchedOption.dispatchEvent(new Event('change', { bubbles: true }));
          if (element instanceof HTMLInputElement) {
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
          }
          resolve(isSelectOptionCommitted(element, value));
          return;
        }

        if (retries < maxRetries) {
          retries++;
          setTimeout(checkAndSelect, 150);
          return;
        }

        console.warn(`[JobFill Warning] No custom option matched for value "${value}". Candidate texts:`, candidates.map(c => c.textContent?.trim()));
        resolve(false);
      };

      setTimeout(checkAndSelect, 300);
    });
  }
}

/**
 * Selects the matching radio button from a group
 */
export function fillCustomRadios(value: string, doc: Document = document): boolean {
  const trimmed = value?.trim();
  if (!trimmed) return false;

  const radios = Array.from(doc.querySelectorAll('[role="radio"]')) as HTMLElement[];
  for (const radio of radios) {
    const label = radio.textContent?.replace(/\s+/g, ' ').trim() || '';
    if (!label || !matchesRadioOption(label, trimmed)) continue;
    if (radio.getAttribute('aria-checked') === 'true') return true;

    const eventTypes = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
    eventTypes.forEach((type) => {
      radio.dispatchEvent(
        new MouseEvent(type, { bubbles: true, cancelable: true, view: doc.defaultView || window, button: 0 })
      );
    });
    return true;
  }

  return false;
}

export function fillRadio(element: HTMLInputElement, value: string, doc: Document) {
  const name = element.name;
  if (!name) return;

  const radios = Array.from(doc.querySelectorAll(`input[type="radio"][name="${name}"]`)) as HTMLInputElement[];

  for (const radio of radios) {
    const label = getLabelText(radio, doc) || radio.value;
    if (matchesRadioOption(label, value) || matchesRadioOption(radio.value, value)) {
      radio.checked = true;
      radio.dispatchEvent(new Event('click', { bubbles: true }));
      radio.dispatchEvent(new Event('change', { bubbles: true }));
      break;
    }
  }
}

/**
 * Toggles a checkbox based on yes/no or matching text
 */
export function fillCheckbox(element: HTMLInputElement, value: string): boolean {
  const valLower = value.toLowerCase().trim();
  const shouldCheck = ['yes', 'true', '1', 'check', 'checked', 'agree'].includes(valLower);

  if (element.checked === shouldCheck) return true;

  element.checked = shouldCheck;
  element.dispatchEvent(new Event('click', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  element.dispatchEvent(new Event('input', { bubbles: true }));
  return element.checked === shouldCheck;
}

/**
 * Helper to set files on HTMLInputElement in a way that React's state tracker recognizes.
 */
function setNativeFiles(element: HTMLInputElement, files: FileList) {
  try {
    const filesSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'files')?.set;
    if (filesSetter) {
      filesSetter.call(element, files);
    } else {
      element.files = files;
    }
  } catch (e) {
    element.files = files;
  }
}

/**
 * Decodes a base64 Data URL and programmatically injects it into a file input.
 */
export function fillFileInput(element: HTMLInputElement, fileData: FileAttachment) {
  try {
    const arr = fileData.base64.split(',');
    const mime = arr[0].match(/:(.*?);/)?.[1] || 'application/octet-stream';
    const bstr = atob(arr[1]);
    let n = bstr.length;
    const u8arr = new Uint8Array(n);
    while (n--) {
      u8arr[n] = bstr.charCodeAt(n);
    }
    const file = new File([u8arr], fileData.name, { type: mime });

    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    
    // Inject file using React-compatible prototype setter
    setNativeFiles(element, dataTransfer.files);

    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.dispatchEvent(new Event('input', { bubbles: true }));
    console.log(`Programmatically attached file: ${fileData.name}`);
  } catch (err: any) {
    console.error('File injection failed, falling back to manual upload helper:', err);
    logToServer({
      level: 'error',
      source: 'autofill:file',
      message: `Resume/file injection failed: ${fileData.name}`,
      stack: err?.stack,
      detail: { error: err?.message }
    });
  }
}

/**
 * Finds a hidden file input associated with a drag-and-drop upload zone.
 */
export function findNearbyFileInput(element: HTMLElement, doc: Document = document): HTMLInputElement | null {
  let node: HTMLElement | null = element;
  for (let depth = 0; depth < 8 && node; depth++) {
    const localFile = node.querySelector('input[type="file"]') as HTMLInputElement | null;
    if (localFile) return localFile;
    node = node.parentElement;
  }

  const labelHint = `${element.getAttribute('aria-label') || ''} ${element.id}`.toLowerCase();
  const desiredKind = detectUploadKindFromHint(labelHint);
  const files = Array.from(doc.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
  if (desiredKind) {
    const matched = files.find((input) => detectFileInputUploadKind(input, doc) === desiredKind);
    if (matched) return matched;
  }
  return (
    files.find((input) => {
      const hint = `${input.id} ${input.name} ${input.getAttribute('aria-label') || ''}`.toLowerCase();
      if (/resume|cv|cover/i.test(labelHint) && /resume|cv|cover/i.test(hint)) return true;
      return input.closest('form') === element.closest('form');
    }) ?? null
  );
}

/**
 * Highlights a form control on the page with a clean, themed indicator border.
 */
export function highlightField(element: HTMLElement, confidence: 'high' | 'medium' | 'low') {
  const colors = {
    high: '#10b981', // green
    medium: '#f59e0b', // orange
    low: '#ef4444' // red (needs answer)
  };

  const color = colors[confidence];
  element.style.outline = `2px solid ${color}`;
  element.style.outlineOffset = '2px';
  element.style.transition = 'outline 0.3s ease';
}

/**
 * Wipes out highlights from all form fields.
 */
export function clearHighlights(doc: Document) {
  const controls = doc.querySelectorAll('input, textarea, select');
  controls.forEach((el) => {
    (el as HTMLElement).style.outline = '';
  });
}
