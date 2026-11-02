import { ScannedField, getLabelText } from './domScanner';
import { resolveFieldLabel } from './fieldInference';

const OPTIONAL_ADDRESS_RE = /address\s*line\s*2|address\s*2\b|apt(\.|artment)?|suite|unit\b/i;
const ADDRESS_FIELD_RE =
  /^(address|street|city|state|province|zip|postal|postcode|country)\b|address\s*line|region of residence|country\/region|mailing address/i;

export function isOptionalAddressField(label: string): boolean {
  return OPTIONAL_ADDRESS_RE.test(label.replace(/\*+$/, '').trim());
}

export function isAddressRelatedField(label: string): boolean {
  const normalized = label.replace(/\*+$/, '').replace(/\s+/g, ' ').trim().toLowerCase();
  if (/email/.test(normalized)) return false;
  return ADDRESS_FIELD_RE.test(normalized);
}

export function isFieldRequired(field: ScannedField, doc: Document): boolean {
  const el = field.element;
  const label = resolveFieldLabel(field, doc) || field.labelText || getLabelText(el, doc);

  if (/\*/.test(label)) return true;

  if (
    el instanceof HTMLInputElement ||
    el instanceof HTMLTextAreaElement ||
    el instanceof HTMLSelectElement
  ) {
    if (el.required) return true;
    if (el.getAttribute('aria-required') === 'true') return true;
  }

  if (el.id) {
    const linked = doc.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (linked && /\*/.test(linked.textContent || '')) return true;
  }

  const combobox = el.closest('[role="combobox"]') as HTMLElement | null;
  if (combobox) {
    const comboboxLabel = getLabelText(combobox, doc) || resolveFieldLabel({ ...field, element: combobox }, doc);
    if (/\*/.test(comboboxLabel)) return true;
  }

  return false;
}

/** Skip optional address lines; for address sections only autofill required markers. */
export function shouldAutofillField(field: ScannedField, doc: Document): boolean {
  const label = resolveFieldLabel(field, doc) || field.labelText || '';

  if (isOptionalAddressField(label)) return false;
  if (/\(optional\)/i.test(label)) return false;

  if (isAddressRelatedField(label)) {
    return isFieldRequired(field, doc);
  }

  return true;
}
