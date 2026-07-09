import { ScannedField, getLabelText } from './domScanner';

const FILLED_INPUT_SELECTOR =
  'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea';

function readElementValue(element: HTMLInputElement | HTMLTextAreaElement): string {
  return element.value?.trim() || '';
}

function readSelectLikeValue(element: HTMLElement): string {
  if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
    const direct = readElementValue(element);
    if (direct) return direct;
  }

  const text = element.textContent?.replace(/\s+/g, ' ').trim() || '';
  if (text && !/^(select\.\.\.|select|search|textbox)$/i.test(text)) {
    return text;
  }

  return '';
}

/** Read the value currently shown for a scanned field, including nearby inputs in custom ATS widgets. */
export function readFieldDisplayValue(field: ScannedField, doc: Document): string {
  const el = field.element;

  if (field.type === 'checkbox' && el instanceof HTMLInputElement) {
    return el.checked ? 'Yes' : '';
  }

  if (field.type === 'select') {
    return readSelectLikeValue(el);
  }

  if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
    const direct = readElementValue(el);
    if (direct) return direct;
  }

  if (field.name) {
    const named = doc.querySelector(
      `${FILLED_INPUT_SELECTOR}[name="${CSS.escape(field.name)}"]`
    ) as HTMLInputElement | HTMLTextAreaElement | null;
    if (named) {
      const namedValue = readElementValue(named);
      if (namedValue) return namedValue;
    }
  }

  if (field.htmlId) {
    const byId = doc.getElementById(field.htmlId) as HTMLInputElement | HTMLTextAreaElement | null;
    if (byId) {
      const byIdValue = readElementValue(byId);
      if (byIdValue) return byIdValue;
    }
  }

  const label = (field.labelText || getLabelText(el, doc)).replace(/\*+$/, '').trim();
  if (label) {
    const labelEl = Array.from(doc.querySelectorAll('label')).find((candidate) => {
      const text = candidate.textContent?.replace(/\s+/g, ' ').trim().replace(/\*+$/, '') || '';
      return text === label || text.includes(label) || label.includes(text);
    });
    if (labelEl) {
      const forId = labelEl.getAttribute('for');
      if (forId) {
        const linked = doc.getElementById(forId) as HTMLInputElement | HTMLTextAreaElement | null;
        const linkedValue = linked ? readElementValue(linked) : '';
        if (linkedValue) return linkedValue;
      }

      const nested = labelEl.querySelector(FILLED_INPUT_SELECTOR) as HTMLInputElement | HTMLTextAreaElement | null;
      const nestedValue = nested ? readElementValue(nested) : '';
      if (nestedValue) return nestedValue;
    }
  }

  let container: HTMLElement | null = el;
  for (let depth = 0; depth < 6 && container; depth++) {
    const localInput = container.querySelector(FILLED_INPUT_SELECTOR) as
      | HTMLInputElement
      | HTMLTextAreaElement
      | null;
    if (localInput) {
      const localValue = readElementValue(localInput);
      if (localValue) return localValue;
    }
    container = container.parentElement;
  }

  return '';
}

export function hasFieldDisplayValue(field: ScannedField, doc: Document): boolean {
  return Boolean(readFieldDisplayValue(field, doc));
}
