import { UserProfile, WorkExperienceEntry } from '../shared/types';
import { fillSelect, fillTextOrTextArea } from './autofillEngine';

const ADD_BUTTON_PATTERNS = [
  /add (?:another )?(?:work|employment|experience|job)/i,
  /add position/i,
  /^\+?\s*add$/i
];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function findAddExperienceButton(doc: Document): HTMLElement | null {
  const candidates = Array.from(
    doc.querySelectorAll('button, a[role="button"], input[type="button"]')
  ) as HTMLElement[];

  for (const el of candidates) {
    if (el.closest('#jobfill-floating-wrapper')) continue;
    const text = (el.textContent || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    if (ADD_BUTTON_PATTERNS.some((p) => p.test(text))) return el;
  }
  return null;
}

function fillExperienceRow(doc: Document, entry: WorkExperienceEntry, index: number): number {
  let filled = 0;
  const containers = Array.from(
    doc.querySelectorAll('[data-automation-id*="workExperience"], fieldset, .work-experience, section')
  ) as HTMLElement[];

  const scope = containers[index] || doc.body;

  const inputs = Array.from(scope.querySelectorAll('input, textarea, select')) as (
    | HTMLInputElement
    | HTMLTextAreaElement
    | HTMLSelectElement
  )[];

  for (const input of inputs) {
    const key = `${input.name || ''} ${input.id || ''} ${input.getAttribute('aria-label') || ''}`.toLowerCase();
    const fillText = (value: string) => {
      if (input instanceof HTMLSelectElement) fillSelect(input, value);
      else if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) {
        fillTextOrTextArea(input, value);
      }
    };
    if (/company|employer|organization/.test(key) && entry.company) {
      fillText(entry.company);
      filled += 1;
    } else if (/title|position|role/.test(key) && entry.jobTitle) {
      fillText(entry.jobTitle);
      filled += 1;
    } else if (/location|city/.test(key) && entry.location) {
      fillText(entry.location);
      filled += 1;
    } else if (/start|from/.test(key) && entry.startDate) {
      fillText(entry.startDate);
      filled += 1;
    } else if (/end|to/.test(key) && entry.endDate) {
      fillText(entry.endDate);
      filled += 1;
    } else if (/description|responsibilit/.test(key) && entry.description) {
      fillText(entry.description);
      filled += 1;
    }
  }

  return filled;
}

/** Fill work history repeaters from profile — clicks Add when needed. */
export async function fillWorkExperienceRepeaters(
  profile: UserProfile,
  doc: Document = document,
  maxEntries = 3
): Promise<number> {
  const entries = profile.workExperience?.filter((e) => e.company?.trim()) || [];
  if (!entries.length) return 0;

  let totalFilled = 0;
  for (let i = 0; i < Math.min(entries.length, maxEntries); i += 1) {
    if (i > 0) {
      const addBtn = findAddExperienceButton(doc);
      if (addBtn) {
        addBtn.click();
        await sleep(900);
      }
    }
    totalFilled += fillExperienceRow(doc, entries[i], i);
  }

  return totalFilled;
}
