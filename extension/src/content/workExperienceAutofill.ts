import { UserProfile, WorkExperienceEntry } from '../shared/types';
import { fillTextOrTextArea, fillCheckbox } from './autofillEngine';
import { getLabelText } from './domScanner';
import { traceStep } from '../shared/actionTrace';

const SECTION_HEADING_RE = /work experience\s*(\d+)/i;

type WorkFieldKey =
  | 'jobTitle'
  | 'company'
  | 'location'
  | 'startDate'
  | 'endDate'
  | 'currentlyEmployed'
  | 'description';

const FIELD_LABELS: { key: WorkFieldKey; pattern: RegExp }[] = [
  { key: 'jobTitle', pattern: /job title/i },
  { key: 'company', pattern: /^company$/i },
  { key: 'location', pattern: /^location$/i },
  { key: 'startDate', pattern: /^from$/i },
  { key: 'endDate', pattern: /^to$/i },
  { key: 'currentlyEmployed', pattern: /currently work here/i },
  { key: 'description', pattern: /role description/i }
];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeLabel(label: string): string {
  return label.replace(/\*/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function findSectionContainer(heading: Element): HTMLElement | null {
  let node: HTMLElement | null = heading as HTMLElement;
  for (let depth = 0; depth < 8 && node; depth++) {
    const inputs = node.querySelectorAll('input, textarea, select');
    if (inputs.length >= 3) return node;
    node = node.parentElement;
  }
  return heading.parentElement;
}

function findWorkExperienceSections(doc: Document): HTMLElement[] {
  const headings = Array.from(
    doc.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, label, span, div, p')
  ).filter((el) => SECTION_HEADING_RE.test(el.textContent?.replace(/\s+/g, ' ') || ''));

  const sections: HTMLElement[] = [];
  const seen = new Set<HTMLElement>();

  for (const heading of headings) {
    const match = heading.textContent?.replace(/\s+/g, ' ').match(SECTION_HEADING_RE);
    if (!match) continue;
    const index = Number(match[1]);
    if (!Number.isFinite(index)) continue;

    const container = findSectionContainer(heading);
    if (!container || seen.has(container)) continue;
    seen.add(container);
    sections[index - 1] = container;
  }

  return sections.filter(Boolean);
}

function findAddWorkExperienceButton(doc: Document): HTMLElement | null {
  const candidates = Array.from(
    doc.querySelectorAll('button, a, [role="button"], input[type="button"]')
  ) as HTMLElement[];

  return (
    candidates.find((el) => {
      const text = el.textContent?.replace(/\s+/g, ' ').trim() || '';
      const aria = el.getAttribute('aria-label') || '';
      return /add\s+(another\s+)?work experience|add\s+experience|add\s+work/i.test(`${text} ${aria}`);
    }) || null
  );
}

async function ensureWorkExperienceSectionCount(targetCount: number, doc: Document): Promise<void> {
  let sections = findWorkExperienceSections(doc);
  let attempts = 0;

  while (sections.length < targetCount && attempts < 6) {
    const addButton = findAddWorkExperienceButton(doc);
    if (!addButton) break;
    addButton.click();
    await sleep(500);
    sections = findWorkExperienceSections(doc);
    attempts++;
  }
}

function collectSectionFields(section: HTMLElement, doc: Document): Map<WorkFieldKey, HTMLElement> {
  const fields = new Map<WorkFieldKey, HTMLElement>();
  const controls = Array.from(
    section.querySelectorAll('input, textarea, select, [role="combobox"], button[aria-haspopup="listbox"]')
  ) as HTMLElement[];

  for (const control of controls) {
    if (control instanceof HTMLInputElement && ['hidden', 'submit', 'button', 'file'].includes(control.type)) {
      continue;
    }

    const label = normalizeLabel(getLabelText(control, doc));
    if (!label) continue;

    for (const { key, pattern } of FIELD_LABELS) {
      if (fields.has(key)) continue;
      if (pattern.test(label)) {
        fields.set(key, control);
        break;
      }
    }
  }

  return fields;
}

function valueForField(key: WorkFieldKey, entry: WorkExperienceEntry): string | boolean {
  switch (key) {
    case 'jobTitle':
      return entry.jobTitle;
    case 'company':
      return entry.company;
    case 'location':
      return entry.location;
    case 'startDate':
      return entry.startDate;
    case 'endDate':
      return entry.endDate || '';
    case 'currentlyEmployed':
      return entry.currentlyEmployed;
    case 'description':
      return entry.description;
    default:
      return '';
  }
}

async function fillWorkExperienceSection(
  section: HTMLElement,
  entry: WorkExperienceEntry,
  doc: Document
): Promise<number> {
  const fields = collectSectionFields(section, doc);
  let filled = 0;

  for (const { key } of FIELD_LABELS) {
    const control = fields.get(key);
    if (!control) continue;

    const value = valueForField(key, entry);

    if (key === 'currentlyEmployed' && control instanceof HTMLInputElement && control.type === 'checkbox') {
      fillCheckbox(control, value ? 'Yes' : 'No');
      filled++;
      await sleep(80);
      continue;
    }

    if (key === 'endDate' && entry.currentlyEmployed) continue;

    if (
      typeof value === 'string' &&
      value.trim() &&
      (control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement)
    ) {
      const didFill = fillTextOrTextArea(control, value.trim());
      if (didFill) filled++;
      await sleep(100);
    }
  }

  return filled;
}

export async function fillWorkExperienceSections(
  profile: UserProfile,
  doc: Document = document,
  operationId?: string
): Promise<number> {
  const entries = profile.workExperience?.filter((entry) => entry.jobTitle?.trim() && entry.company?.trim()) || [];
  if (!entries.length) return 0;

  traceStep(operationId, 'autofill', 'work_experience_start', 'autofill:workExperience', {
    entryCount: entries.length
  });

  await ensureWorkExperienceSectionCount(entries.length, doc);
  const sections = findWorkExperienceSections(doc);

  let filled = 0;
  for (let i = 0; i < Math.min(entries.length, sections.length); i++) {
    const count = await fillWorkExperienceSection(sections[i], entries[i], doc);
    filled += count;
    traceStep(operationId, 'autofill', 'work_experience_section', 'autofill:workExperience', {
      index: i,
      company: entries[i].company,
      filledFields: count
    });
  }

  traceStep(operationId, 'autofill', 'work_experience_end', 'autofill:workExperience', {
    filledFields: filled,
    sectionsFound: sections.length
  });

  return filled;
}
