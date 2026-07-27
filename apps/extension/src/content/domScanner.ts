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
function isGenericControlLabel(text: string): boolean {
  const normalized = text.toLowerCase().trim();
  return ['select...', 'select', 'choose...', 'choose', 'dropdown', 'select an option', 'textbox', 'search'].includes(
    normalized
  );
}

function textFromLabelledByIds(labelledBy: string, doc: Document): string {
  for (const id of labelledBy.split(/\s+/)) {
    const trimmedId = id.trim();
    if (!trimmedId) continue;
    const labelEl = doc.getElementById(trimmedId);
    const text = labelEl?.textContent?.replace(/\s+/g, ' ').trim().replace(/\*+$/, '') || '';
    if (text && !isGenericControlLabel(text) && !OPTION_LABEL_RE.test(text)) {
      return text;
    }
  }
  return '';
}

export function getLabelText(element: HTMLElement, doc: Document): string {
  const selectShell =
    typeof element.closest === 'function'
      ? (element.closest('.select-shell') as HTMLElement | null)
      : null;
  if (selectShell) {
    const reactLabel = selectShell.querySelector('.select__label, label');
    const reactLabelText = reactLabel?.textContent?.replace(/\s+/g, ' ').trim().replace(/\*+$/, '') || '';
    if (reactLabelText && !isGenericControlLabel(reactLabelText)) {
      return reactLabelText;
    }
  }

  if (element.getAttribute('role') === 'combobox' || selectShell) {
    const groupQuestion = getFieldGroupQuestion(element, doc);
    if (groupQuestion) return groupQuestion;
  }

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
  if (ariaLabel && !isGenericControlLabel(ariaLabel)) {
    return ariaLabel;
  }

  const labelledBy = element.getAttribute('aria-labelledby');
  if (labelledBy) {
    const fromIds = textFromLabelledByIds(labelledBy, doc);
    if (fromIds) return fromIds;
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

const OPTION_LABEL_RE = /^(yes|no|true|false)$/i;
const MAX_GROUP_QUESTION_LENGTH = 600;

function extractQuestionText(node: Element): string {
  const text = node.textContent?.replace(/\s+/g, ' ').trim().replace(/\*+$/, '') || '';
  if (
    text.length > 12 &&
    text.length < MAX_GROUP_QUESTION_LENGTH &&
    !OPTION_LABEL_RE.test(text) &&
    !/^(search|textbox|select\.\.\.|select)$/i.test(text)
  ) {
    return text;
  }
  return '';
}

/** Resolve the screening question text for a radio/checkbox group (not the Yes/No option label). */
export function getFieldGroupQuestion(element: HTMLElement, doc: Document): string {
  if (typeof element.closest !== 'function') return '';

  const fieldset = element.closest('fieldset');
  if (fieldset) {
    const legend = fieldset.querySelector('legend');
    const legendText = legend?.textContent?.replace(/\s+/g, ' ').trim().replace(/\*+$/, '') || '';
    if (legendText && !OPTION_LABEL_RE.test(legendText)) return legendText;
  }

  const groupedControl = element.closest('[role="radiogroup"], [role="group"], .select-shell') as HTMLElement | null;
  if (groupedControl) {
    const labelledBy = groupedControl.getAttribute('aria-labelledby');
    if (labelledBy) {
      const labelText = textFromLabelledByIds(labelledBy, doc);
      if (labelText && !OPTION_LABEL_RE.test(labelText)) return labelText;
    }
  }

  let walk: HTMLElement | null = element;
  for (let depth = 0; depth < 8 && walk; depth++) {
    let prev = walk.previousElementSibling;
    while (prev) {
      const text = extractQuestionText(prev);
      if (text) return text;
      prev = prev.previousElementSibling;
    }
    walk = walk.parentElement;
  }

  let node: HTMLElement | null = element.parentElement;
  while (node && node.tagName !== 'BODY') {
    for (const child of Array.from(node.children)) {
      if (child === element || child.contains(element)) continue;
      if (
        child.querySelector('input[type="radio"], input[type="checkbox"], [role="radio"]') &&
        child.contains(element)
      ) {
        continue;
      }

      const text = extractQuestionText(child);
      if (text) return text;
    }
    node = node.parentElement;
  }

  return '';
}

/** @deprecated Use getFieldGroupQuestion */
export const getRadioGroupQuestion = getFieldGroupQuestion;

function addLabelCandidate(labels: string[], text: string): void {
  const cleaned = text.replace(/\*+$/, '').replace(/\s+/g, ' ').trim();
  if (!cleaned || cleaned.length < 3 || isGenericControlLabel(cleaned) || OPTION_LABEL_RE.test(cleaned)) {
    return;
  }
  if (!labels.includes(cleaned)) {
    labels.push(cleaned);
  }
}

/** Collect every label string that might identify a custom combobox (Greenhouse section header + question). */
export function getComboboxLabelCandidates(element: HTMLElement, doc: Document): string[] {
  const labels: string[] = [];
  const selectShell =
    typeof element.closest === 'function'
      ? (element.closest('.select-shell') as HTMLElement | null)
      : null;

  const knownEeoInputLabels: Record<string, string> = {
    gender: 'Gender',
    hispanic_ethnicity: 'Are you Hispanic/Latino?',
    veteran_status: 'Veteran Status',
    disability_status: 'Disability Status',
    race: 'Please identify your race'
  };
  if (element.id && knownEeoInputLabels[element.id]) {
    addLabelCandidate(labels, knownEeoInputLabels[element.id]);
  }

  // Prefer explicit select labels (Greenhouse .select__label) before aria/heuristic text that may pick up sibling fields (e.g. "Phone" on Country).
  if (selectShell) {
    selectShell.querySelectorAll('.select__label, label, legend').forEach((node) => {
      addLabelCandidate(labels, node.textContent || '');
    });
  }

  addLabelCandidate(labels, getLabelText(element, doc));
  addLabelCandidate(labels, getFieldGroupQuestion(element, doc));

  // Previous-sibling question headers (Greenhouse screening sections) before ancestor field scans.
  let walk: HTMLElement | null = element;
  for (let depth = 0; depth < 6 && walk; depth++) {
    let prev = walk.previousElementSibling;
    while (prev) {
      addLabelCandidate(labels, extractQuestionText(prev));
      prev = prev.previousElementSibling;
    }
    walk = walk.parentElement;
  }

  if (selectShell) {
    const fieldRoot = selectShell.closest(
      'li, .application-field, .job-application-field, [class*="application-question"], [class*="question-field"]'
    ) as HTMLElement | null;
    if (fieldRoot) {
      fieldRoot
        .querySelectorAll(':scope > label, :scope > legend, :scope > h3, :scope > h4, :scope > p, :scope > .label')
        .forEach((node) => {
          if (selectShell.contains(node)) return;
          addLabelCandidate(labels, node.textContent || '');
        });
    }
  }

  return labels;
}

export function isGreenhouseSelectPhantom(element: HTMLElement): boolean {
  if (element.classList?.contains('select__placeholder')) return true;
  const shell =
    typeof element.closest === 'function'
      ? (element.closest('.select-shell') as HTMLElement | null)
      : null;
  if (!shell) return false;
  const input = shell.querySelector('input.select__input[role="combobox"], input[role="combobox"].select__input');
  return Boolean(input && input !== element);
}

export function isInstructionalScanLabel(label: string): boolean {
  const normalized = label.replace(/\s+/g, ' ').trim();
  if (normalized.length > 260) return true;
  if (/voluntary self-identification for government reporting purposes/i.test(normalized)) return true;
  if (/race & ethnicity definitions|classification of protected categories|public burden statement/i.test(normalized)) {
    return true;
  }
  return false;
}

export function isExtensionUiElement(element: HTMLElement): boolean {
  if (typeof element.closest !== 'function') return false;
  return Boolean(
    element.closest(
      '#jobfill-floating-wrapper, #jobfill-skipped-panel, [id^="jobfill-"], [id^="jf-"], [class*="jobfill"]'
    )
  );
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
    if (isExtensionUiElement(input)) continue;

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

    if (isGreenhouseSelectPhantom(input)) {
      continue;
    }

    const labelCandidates = getComboboxLabelCandidates(input, doc);
    const directLabel = labelCandidates[0] || getLabelText(input, doc);
    let resolvedLabel = directLabel;

    if (isInstructionalScanLabel(resolvedLabel)) {
      continue;
    }

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

      const groupQuestion = getFieldGroupQuestion(input, doc);

      scanned.push({
        id: Math.random().toString(36).substring(2, 9),
        element: input,
        type: 'radio',
        labelText: groupQuestion || resolvedLabel || name,
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
      resolvedLabel = getFieldGroupQuestion(input, doc) || resolvedLabel;
      options = [resolvedLabel || 'Yes'];
    }

    scanned.push({
      id: Math.random().toString(36).substring(2, 9),
      element: input,
      type,
      labelText: resolvedLabel,
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
    if (el.closest('.select-shell')) continue;
    if (el.classList.contains('select__placeholder')) continue;

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
        if (scanned.some((s) => s.element === container)) continue;
        if (isGreenhouseSelectPhantom(container)) continue;
        const labelText = getLabelText(container, doc);
        if (!labelText || isInstructionalScanLabel(labelText)) continue;
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
