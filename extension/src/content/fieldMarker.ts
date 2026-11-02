import { highlightField } from './autofillEngine';

export const FIELD_MARKER_ATTR = 'data-applypilot-field-id';

export function resolveScrollTarget(element: HTMLElement): HTMLElement {
  if (element.getAttribute('role') === 'combobox') return element;

  const combobox = element.closest('[role="combobox"]') as HTMLElement | null;
  if (combobox) return combobox;

  const section = element.closest(
    'fieldset, [class*="question"], [class*="field-group"], [class*="form-field"], li'
  ) as HTMLElement | null;
  if (section && section !== document.body) return section;

  return element;
}

export function stampFieldMarker(element: HTMLElement, fieldId: string): void {
  if (!fieldId) return;
  resolveScrollTarget(element).setAttribute(FIELD_MARKER_ATTR, fieldId);
}

export function scrollToMarkedField(doc: Document, fieldId: string): boolean {
  if (!fieldId) return false;

  const marked = doc.querySelector(
    `[${FIELD_MARKER_ATTR}="${CSS.escape(fieldId)}"]`
  ) as HTMLElement | null;

  if (marked) {
    marked.scrollIntoView({ behavior: 'smooth', block: 'center' });
    highlightField(marked, 'low');
    window.setTimeout(() => {
      marked.style.outline = '';
      marked.style.outlineOffset = '';
    }, 3200);
    return true;
  }

  return false;
}
