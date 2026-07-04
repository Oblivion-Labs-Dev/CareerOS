import { ScannedField, getLabelText } from './domScanner';
import { FileAttachment } from '../shared/types';
import { isSynonymMatch, matchesCustomOption, matchesRadioOption } from './autofillEngine.matching';
import {
  isPlaceholderSelectOption,
  matchesStateOption,
  matchesLocationOption,
  scoreLocationOption,
  resolveLocationCity
} from '../shared/usStates';
import { logToServer } from '../shared/serverLog';

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
    } else if (matchesCustomOption(text, value)) {
      score = 15;
    } else {
      const valLower = value.toLowerCase().trim();
      const textLower = text.toLowerCase();
      if (valLower && (textLower === valLower || textLower.includes(valLower))) {
        score = 8;
      }
    }

    if (score > 0 && (!best || score > best.score)) {
      best = { el, score };
    }
  }

  return best?.el;
}

function clickListboxOption(matchedElement: HTMLElement, input: HTMLInputElement): void {
  console.log(`[JobFill] Selecting listbox option: "${matchedElement.textContent?.trim()}"`);
  const eventTypes = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
  eventTypes.forEach((type) => {
    matchedElement.dispatchEvent(
      new MouseEvent(type, {
        bubbles: true,
        cancelable: true,
        view: document.defaultView || window,
        button: 0,
        buttons: 1
      })
    );
  });
  matchedElement.dispatchEvent(new Event('change', { bubbles: true }));
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
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

  const fillValue =
    element instanceof HTMLInputElement &&
    (element.type === 'tel' || /phone|tel|mobile/i.test(element.autocomplete))
      ? normalizePhoneForInput(value)
      : element instanceof HTMLInputElement && /[\d+() -]{7,}/.test(value) && value.replace(/\D/g, '').length >= 10
        ? normalizePhoneForInput(value)
        : value;

  const isLocationCombobox =
    element instanceof HTMLInputElement &&
    (element.getAttribute('role') === 'combobox' ||
      element.getAttribute('aria-autocomplete') === 'list' ||
      /start typing/i.test(element.getAttribute('placeholder') || '') ||
      /location|city|address|residence/i.test(
        `${element.getAttribute('aria-label') || ''} ${element.id} ${element.name}`
      ));

  const typeValue =
    isLocationCombobox && /,/.test(value) ? resolveLocationCity(value) : fillValue;
  const locationContext = isLocationCombobox && /,/.test(value) ? value : undefined;

  element.focus();
  dispatchReactInput(element, typeValue);

  if (element instanceof HTMLInputElement) {
    const usesAutocomplete =
      element.getAttribute('role') === 'combobox' ||
      element.getAttribute('aria-autocomplete') === 'list' ||
      /start typing/i.test(element.getAttribute('placeholder') || '') ||
      /location|city|address|residence/i.test(
        `${element.getAttribute('aria-label') || ''} ${element.getAttribute('placeholder') || ''} ${element.id}`
      );

    if (usesAutocomplete) {
      selectAutocompleteOption(element, typeValue, locationContext);
    }
  }

  return true;
}

async function fillSearchCombobox(element: HTMLInputElement, value: string, locationContext?: string): Promise<boolean> {
  const locContext = locationContext || (/,/.test(value) ? value : undefined);
  const typeValue = locContext ? resolveLocationCity(locContext) : value;

  console.log(`[JobFill] Filling search combobox #${element.id} with "${typeValue}"`);
  closeOpenListboxes();
  element.focus();
  element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  dispatchReactInput(element, typeValue);
  element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: typeValue }));

  const attemptSelect = (delayMs: number) =>
    new Promise<boolean>((resolve) => {
      setTimeout(() => {
        const listboxId = element.getAttribute('aria-controls') || element.getAttribute('aria-owns');
        const searchRoot = listboxId ? document.getElementById(listboxId) : document;
        const candidates = Array.from(searchRoot?.querySelectorAll('[role="option"], li') ?? []) as HTMLElement[];

        const matchedOption = pickBestListboxOption(candidates, typeValue, locContext);
        if (matchedOption) {
          clickListboxOption(matchedOption, element);
          resolve(true);
          return;
        }
        resolve(false);
      }, delayMs);
    });

  if (await attemptSelect(500)) return true;
  if (await attemptSelect(1000)) return true;
  return comboboxShowsValue(element, locContext || typeValue);
}

function comboboxShowsValue(element: HTMLElement, value: string): boolean {
  const root = (element.closest('[role="combobox"]') as HTMLElement | null) || element;
  const parts = [
    root.textContent?.replace(/\s+/g, ' ').trim() || '',
    element instanceof HTMLInputElement ? element.value?.trim() || '' : ''
  ];
  const child = root.querySelector('p, span');
  if (child?.textContent?.trim()) parts.push(child.textContent.trim());
  return parts.some(
    (part) =>
      part &&
      (matchesCustomOption(part, value) || (/,/.test(value) && matchesLocationOption(part, value)))
  );
}

function resolveSearchComboboxInput(element: HTMLElement): HTMLInputElement | null {
  if (element instanceof HTMLInputElement) {
    if (element.getAttribute('role') === 'combobox' || element.getAttribute('data-input') === 'select-search-input') {
      return element;
    }
  }
  return element.querySelector(
    'input[role="combobox"], input[data-input="select-search-input"]'
  ) as HTMLInputElement | null;
}

function closeOpenListboxes(): void {
  const escape = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true });
  document.activeElement?.dispatchEvent(escape);
  document.dispatchEvent(escape);
}

export async function fillSelect(element: HTMLElement, value: string): Promise<boolean> {
  console.log(`[JobFill] fillSelect called. Element: ${element.tagName}, ID: ${element.id}, Value: ${value}`);
  if (element instanceof HTMLSelectElement) {
    let bestIndex = -1;

    for (let i = 0; i < element.options.length; i++) {
      const opt = element.options[i];
      const optVal = opt.value;
      const optText = opt.text;

      if (isPlaceholderSelectOption(optText, optVal)) continue;

      if (
        isSynonymMatch(optVal, value) ||
        isSynonymMatch(optText, value) ||
        matchesStateOption(optText, value) ||
        matchesStateOption(optVal, value)
      ) {
        bestIndex = i;
        break;
      }
    }

    if (bestIndex !== -1) {
      console.log(`[JobFill] Setting native select index to ${bestIndex}`);
      element.selectedIndex = bestIndex;
      element.dispatchEvent(new Event('change', { bubbles: true }));
      element.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }
    return false;
  } else {
    const searchInput = resolveSearchComboboxInput(element);
    if (searchInput) {
      const locationContext = /,/.test(value) ? value : undefined;
      const searchFilled = await fillSearchCombobox(searchInput, value, locationContext);
      if (searchFilled || comboboxShowsValue(element, locationContext || value)) return true;
    }

    // Custom DIV/button combobox filling
    console.log('[JobFill] Triggering mousedown and keyboard open sequence on custom select control and its children');

    closeOpenListboxes();
    await new Promise((r) => setTimeout(r, 50));

    // Focus the elements first to activate framework listeners
    element.focus();
    
    // Dispatch open events to both the container and the inner text/placeholder child to ensure React handles it
    const openTargets = [element];
    const innerClickable = element.querySelector('p, span, button, div') as HTMLElement;
    if (innerClickable && innerClickable !== element) {
      innerClickable.focus();
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
      const maxRetries = 10;

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
        const candidates = Array.from(searchRoot.querySelectorAll('[role="option"], li')) as HTMLElement[];
        console.log(`[JobFill Debug] Found ${candidates.length} custom option candidates in scope`);
        
        const matchedOption = candidates.find((el) => {
          if (el === element || el.contains(element)) return false;
          const text = el.textContent?.trim() || '';
          return text && matchesCustomOption(text, value);
        });

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
          resolve(true);
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
export function fillCheckbox(element: HTMLInputElement, value: string) {
  const valLower = value.toLowerCase().trim();
  const shouldCheck = ['yes', 'true', '1', 'check', 'checked', 'agree'].includes(valLower);

  element.checked = shouldCheck;
  element.dispatchEvent(new Event('change', { bubbles: true }));
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
  const files = Array.from(doc.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
  return (
    files.find((input) => {
      const hint = `${input.id} ${input.name} ${input.getAttribute('aria-label') || ''}`.toLowerCase();
      if (/resume|cv|cover/i.test(labelHint) && /resume|cv|cover/i.test(hint)) return true;
      return input.closest('form') === element.closest('form');
    }) ?? files[0] ??
    null
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
