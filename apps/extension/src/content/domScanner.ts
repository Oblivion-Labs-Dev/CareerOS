export interface ScannedField {
  id: string; // Internal temporary ID
  element: HTMLElement; // Input element
  type: 'text' | 'textarea' | 'select' | 'radio' | 'checkbox' | 'file';
  labelText: string;
  placeholder: string;
  name: string;
  htmlId: string;
  autocomplete: string;
  dataInput?: string;
  options?: string[]; // Options list for select, radio, or checkboxes
}

/**
 * Searches the DOM to find the label text of an element
 */
export function getLabelText(element: HTMLElement, doc: Document): string {
  // 1. Check parent wrapping label
  let parent = element.parentElement;
  while (parent) {
    if (parent.tagName === 'LABEL') {
      return parent.textContent?.replace(/\s+/g, ' ').trim() || '';
    }
    parent = parent.parentElement;
  }

  // 2. Check for matching label[for="id"]
  if (element.id) {
    const label = doc.querySelector(`label[for="${element.id}"]`);
    if (label) {
      return label.textContent?.replace(/\s+/g, ' ').trim() || '';
    }
  }

  // 3. Check aria-labelledby or aria-label
  const ariaLabel = element.getAttribute('aria-label');
  if (
    ariaLabel &&
    !['select...', 'select', 'choose...', 'choose', 'dropdown', 'select an option', 'textbox', 'search'].includes(
      ariaLabel.toLowerCase().trim()
    )
  ) {
    return ariaLabel;
  }

  const labelledBy = element.getAttribute('aria-labelledby');
  if (labelledBy) {
    const labelEl = doc.getElementById(labelledBy);
    if (labelEl) return labelEl.textContent?.replace(/\s+/g, ' ').trim() || '';
  }

  // 4. Fallback: Search siblings or preceding text
  const previousSibling = element.previousElementSibling;
  if (previousSibling && (previousSibling.tagName === 'SPAN' || previousSibling.tagName === 'DIV')) {
    const txt = previousSibling.textContent?.trim();
    if (txt && txt.length < 100) return txt.replace(/\*+$/, '').trim();
  }

  // 5. Walk up the tree for Rippling-style field labels above the control
  let node: HTMLElement | null = element;
  while (node && node.tagName !== 'BODY') {
    let sibling = node.previousElementSibling;
    while (sibling) {
      const txt = sibling.textContent?.replace(/\s+/g, ' ').trim() || '';
      const normalized = txt.toLowerCase();
      if (
        txt.length > 1 &&
        txt.length < 100 &&
        !['select...', 'select', 'search', 'textbox', 'choose...', 'choose'].includes(normalized)
      ) {
        return txt.replace(/\*+$/, '').trim();
      }
      sibling = sibling.previousElementSibling;
    }
    node = node.parentElement;
  }

  return '';
}

/**
 * Scans the page and returns all input fields
 */
export function scanPage(doc: Document): ScannedField[] {
  const scanned: ScannedField[] = [];
  const processedRadioNames = new Set<string>();

  // Find all candidate form controls, including custom comboboxes and aria select listboxes
  const inputs = Array.from(
    new Set(
      doc.querySelectorAll(
        'input, textarea, select, [role="combobox"], button[aria-haspopup="listbox"], button[aria-haspopup="true"]'
      )
    )
  ) as HTMLElement[];

  for (const input of inputs) {
    const tagName = input.tagName.toUpperCase();
    const typeAttr = input.getAttribute('type') || '';
    const name = input.getAttribute('name') || '';
    const htmlId = input.id || '';
    const placeholder = input.getAttribute('placeholder') || '';
    const autocomplete = input.getAttribute('autocomplete') || '';
    const dataInput = input.getAttribute('data-input') || '';

    // Filter hidden fields or actions
    if (tagName === 'INPUT' && (typeAttr === 'hidden' || typeAttr === 'submit' || typeAttr === 'button')) {
      continue;
    }

    const labelText = getLabelText(input, doc);

    // Group radio buttons by name
    if (tagName === 'INPUT' && typeAttr === 'radio') {
      if (name && processedRadioNames.has(name)) continue;
      if (name) processedRadioNames.add(name);

      // Collect all radio options with this name
      const siblings = Array.from(doc.querySelectorAll(`input[type="radio"][name="${name}"]`)) as HTMLInputElement[];
      const options = siblings.map(sibling => {
        const optionLabel = getLabelText(sibling, doc) || sibling.value;
        return optionLabel;
      });

      scanned.push({
        id: Math.random().toString(36).substring(2, 9),
        element: input,
        type: 'radio',
        labelText: labelText || name,
        placeholder: '',
        name,
        htmlId,
        autocomplete,
        dataInput,
        options
      });
      continue;
    }

    // Identify standard field types
    let type: ScannedField['type'] = 'text';
    let options: string[] | undefined;

    if (tagName === 'TEXTAREA') {
      type = 'textarea';
    } else if (
      tagName === 'SELECT' ||
      input.getAttribute('role') === 'combobox' ||
      input.getAttribute('aria-haspopup') === 'listbox' ||
      input.getAttribute('aria-haspopup') === 'true'
    ) {
      type = 'select';
      if (tagName === 'SELECT') {
        options = Array.from((input as HTMLSelectElement).options)
          .map(o => o.text.trim())
          .filter(t => t !== '');
      } else {
        // Try to collect custom option texts if listbox is pre-rendered
        const listboxId = input.getAttribute('aria-controls');
        const listbox = listboxId ? doc.getElementById(listboxId) : null;
        if (listbox) {
          options = Array.from(listbox.querySelectorAll('[role="option"], li'))
            .map(o => o.textContent?.trim() || '')
            .filter(t => t !== '');
        }
      }
    } else if (tagName === 'INPUT' && typeAttr === 'file') {
      type = 'file';
    } else if (tagName === 'INPUT' && typeAttr === 'checkbox') {
      type = 'checkbox';
      options = [labelText || 'Yes'];
    }

    scanned.push({
      id: Math.random().toString(36).substring(2, 9),
      element: input,
      type,
      labelText,
      placeholder,
      name,
      htmlId,
      autocomplete,
      dataInput
    });
  }

  // Scan custom styled select dropdown elements (divs/buttons with Select... placeholder)
  const customControls = Array.from(doc.querySelectorAll('div, button, span, p')) as HTMLElement[];
  for (const el of customControls) {
    const text = el.textContent?.trim();
    if (
      (text === 'Select...' || text === 'Select') &&
      el.children.length <= 2 &&
      !el.querySelector('input, textarea, select')
    ) {
      // Find the closest ancestor combobox wrapper or button
      let container: HTMLElement | null = el;
      while (container && container.tagName !== 'BODY') {
        if (
          container.getAttribute('role') === 'combobox' ||
          container.getAttribute('aria-haspopup') ||
          container.tagName === 'BUTTON' ||
          container.classList.toString().includes('select') ||
          container.classList.toString().includes('dropdown')
        ) {
          break;
        }
        container = container.parentElement;
      }

      if (container && container.tagName !== 'BODY') {
        if (scanned.some(s => s.element === container)) continue;
        const labelText = getLabelText(container, doc);
        if (labelText) {
          scanned.push({
            id: Math.random().toString(36).substring(2, 9),
            element: container,
            type: 'select',
            labelText,
            placeholder: 'Select...',
            name: labelText.toLowerCase().replace(/\s+/g, '_'),
            htmlId: container.id || '',
            autocomplete: '',
            options: []
          });
        }
      }
    }
  }

  scanUploadDropZones(doc, scanned);

  return scanned;
}

function findFileInputNear(element: HTMLElement, doc: Document): HTMLInputElement | null {
  let node: HTMLElement | null = element;
  for (let depth = 0; depth < 8 && node; depth++) {
    const localFile = node.querySelector('input[type="file"]') as HTMLInputElement | null;
    if (localFile) return localFile;
    node = node.parentElement;
  }
  const files = Array.from(doc.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
  return files[0] ?? null;
}

function scanUploadDropZones(doc: Document, scanned: ScannedField[]): void {
  const seenElements = new Set(scanned.map((s) => s.element));

  for (const fileInput of Array.from(doc.querySelectorAll('input[type="file"]')) as HTMLInputElement[]) {
    if (seenElements.has(fileInput)) continue;
    const labelText = getLabelText(fileInput, doc) || 'Resume';
    scanned.push({
      id: Math.random().toString(36).substring(2, 9),
      element: fileInput,
      type: 'file',
      labelText,
      placeholder: '',
      name: fileInput.name || '',
      htmlId: fileInput.id || '',
      autocomplete: '',
      dataInput: fileInput.getAttribute('data-input') || ''
    });
    seenElements.add(fileInput);
  }

  for (const el of Array.from(doc.querySelectorAll('div, section, label, button, span')) as HTMLElement[]) {
    const text = el.textContent?.replace(/\s+/g, ' ').trim() || '';
    if (!/drop or select/i.test(text)) continue;
    if (el.querySelector('input[type="file"]')) continue;

    const labelText = getLabelText(el, doc) || text;
    const isResume =
      /résumé|resume|\bcv\b/i.test(labelText) ||
      /résumé|resume|\bcv\b/i.test(text) ||
      /résumé|resume|\bcv\b/i.test(el.closest('section, fieldset, form')?.textContent || '');
    if (!isResume) continue;

    const target = findFileInputNear(el, doc) ?? el;
    if (seenElements.has(target)) continue;

    scanned.push({
      id: Math.random().toString(36).substring(2, 9),
      element: target,
      type: 'file',
      labelText: /résumé|resume|\bcv\b/i.test(labelText) ? labelText : 'Résumé',
      placeholder: text,
      name: target instanceof HTMLInputElement ? target.name : 'resume_upload',
      htmlId: target.id || '',
      autocomplete: '',
      dataInput: target.getAttribute?.('data-input') || ''
    });
    seenElements.add(target);
  }
}
