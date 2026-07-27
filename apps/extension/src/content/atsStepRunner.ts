/** Multi-step ATS navigation — click Next/Continue after filling a step (free, no AI). */

const NEXT_SELECTORS = [
  'button[data-automation-id="bottom-navigation-next-button"]',
  'button[data-automation-id="pageFooterNextButton"]',
  'button[aria-label*="Next" i]',
  'button[aria-label*="Continue" i]',
  'input[type="button"][value*="Next" i]',
  'input[type="submit"][value*="Continue" i]',
  'button[type="button"]',
  'button[type="submit"]'
];

const NEXT_PATTERNS = [
  /^next$/i,
  /^continue$/i,
  /^save and continue$/i,
  /^review$/i,
  /^proceed$/i
];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isVisible(el: HTMLElement): boolean {
  if (!el.offsetParent && el.getAttribute('aria-hidden') === 'true') return false;
  const style = window.getComputedStyle(el);
  return style.display !== 'none' && style.visibility !== 'hidden';
}

function labelOf(el: HTMLElement): string {
  return (
    el.getAttribute('aria-label') ||
    el.textContent ||
    (el instanceof HTMLInputElement ? el.value : '') ||
    ''
  )
    .replace(/\s+/g, ' ')
    .trim();
}

function findNextButton(doc: Document): HTMLElement | null {
  for (const selector of NEXT_SELECTORS) {
    for (const el of Array.from(doc.querySelectorAll(selector))) {
      if (!(el instanceof HTMLElement)) continue;
      if (!isVisible(el)) continue;
      if (el.closest('#jobfill-floating-wrapper')) continue;
      const label = labelOf(el);
      if (NEXT_PATTERNS.some((p) => p.test(label))) return el;
    }
  }
  return null;
}

export interface StepRunnerResult {
  clicked: boolean;
  buttonLabel?: string;
}

/** Attempt one Next/Continue click after autofill — user still submits manually. */
export async function tryAdvanceAtsStep(doc: Document = document): Promise<StepRunnerResult> {
  await sleep(800);
  const button = findNextButton(doc);
  if (!button) return { clicked: false };

  const label = labelOf(button);
  if (/submit|apply now|send application|complete application/i.test(label)) {
    return { clicked: false, buttonLabel: label };
  }

  button.click();
  await sleep(1200);
  return { clicked: true, buttonLabel: label };
}

export async function runMultiStepAtsPass(
  doc: Document = document,
  maxSteps = 3
): Promise<number> {
  let advanced = 0;
  for (let i = 0; i < maxSteps; i += 1) {
    const result = await tryAdvanceAtsStep(doc);
    if (!result.clicked) break;
    advanced += 1;
    await sleep(1500);
  }
  return advanced;
}
