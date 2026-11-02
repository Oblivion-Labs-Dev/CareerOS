import {
  test,
  expect,
  attachConsoleCollector,
  type ConsoleIssue
} from './extension.fixture';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ANDURIL_URL =
  'https://job-boards.greenhouse.io/andurilindustries/jobs/4754841007?gh_jid=4754841007';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPORT_PATH = path.join(__dirname, '..', 'e2e-reports', 'anduril-autofill-report.json');

/** Profile aligned with extension dashboard — confirm screening answers with user if unsure. */
const testProfile = {
  firstName: 'Akshay',
  lastName: 'Borse',
  fullName: 'Akshay Borse',
  email: 'amsborse@gmail.com',
  phone: '+1 4253369852',
  location: 'Seattle, WA',
  linkedin: 'https://www.linkedin.com/in/amsborse/',
  github: 'https://github.com/amsborse',
  portfolio: 'https://amsborse.github.io/resume',
  workAuthorization: 'Yes',
  sponsorship: 'Yes',
  yearsExperience: '7',
  currentTitle: 'Senior Software Engineer',
  targetRole: 'Senior Software Engineer',
  currentCompany: 'Microsoft',
  salaryExpectations: '',
  pronouns: 'He/him/his',
  gender: 'Male',
  raceEthnicity: 'Asian',
  hispanic: 'No',
  veteran: 'I am not a protected veteran',
  disability: "No, I don't have a disability",
  smsConsent: 'No - I do not consent to receiving text messages',
  customFields: { country: 'United States' }
};

async function seedAutofillProfile(
  worker: { evaluate: (fn: (profile: typeof testProfile) => Promise<void>, profile: typeof testProfile) => Promise<void> },
  profile: typeof testProfile
): Promise<void> {
  await worker.evaluate(async (p) => {
    await chrome.storage.local.set({ jobfill_profile: p });
  }, profile);

  const response = await fetch('http://127.0.0.1:8000/api/db', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, documents: {} })
  });
  if (!response.ok) {
    throw new Error(`Failed to seed API profile: ${response.status} ${await response.text()}`);
  }
}

type FieldState = {
  label: string;
  kind: 'text' | 'select' | 'file' | 'textarea' | 'radio' | 'checkbox';
  value: string;
  unfilled: boolean;
  required: boolean;
};

async function scrollFullForm(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(async () => {
    const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const step = Math.max(200, Math.floor(window.innerHeight * 0.75));
    for (let y = 0; y < document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await delay(120);
    }
    window.scrollTo(0, document.body.scrollHeight);
    await delay(300);
    window.scrollTo(0, 0);
    await delay(200);
  });
}

async function collectGreenhouseFieldStates(page: import('@playwright/test').Page): Promise<FieldState[]> {
  await scrollFullForm(page);
  return page.evaluate(() => {
    const PLACEHOLDER = /^(select\.\.\.|select|choose|search|textbox)$/i;

    function normalize(text: string): string {
      return text.replace(/\s+/g, ' ').trim();
    }

    function isRequired(label: string): boolean {
      return /\*/.test(label);
    }

    function extractQuestionText(node: Element): string {
      const text = normalize(node.textContent || '');
      if (!text || text.length > 220) return '';
      return text;
    }

    function getComboboxLabel(shell: Element): string {
      const labels: string[] = [];
      shell.querySelectorAll('.select__label, label, legend').forEach((node) => {
        const t = extractQuestionText(node);
        if (t) labels.push(t);
      });
      const fieldRoot = shell.closest('[class*="field"], .application-field, li, fieldset');
      if (fieldRoot) {
        fieldRoot.querySelectorAll('label, legend, h3, h4, p').forEach((node) => {
          if (shell.contains(node)) return;
          const t = extractQuestionText(node);
          if (t && t.length < 180) labels.push(t);
        });
      }
      let walk: Element | null = shell;
      for (let i = 0; i < 6 && walk; i++) {
        let prev = walk.previousElementSibling;
        while (prev) {
          const t = extractQuestionText(prev);
          if (t) labels.push(t);
          prev = prev.previousElementSibling;
        }
        walk = walk.parentElement;
      }
      return labels.find((l) => l.length < 180) || labels[0] || 'Unknown';
    }

    function comboboxDisplay(shell: Element): string {
      const single = shell.querySelector('.select__single-value, [class*="single-value"]');
      const text = single?.textContent ? normalize(single.textContent) : '';
      if (text && !PLACEHOLDER.test(text)) return text;
      return '';
    }

    function getLabel(el: Element): string {
      const id = el.getAttribute('id');
      if (id) {
        const linked = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        if (linked?.textContent) return normalize(linked.textContent);
      }
      return normalize(el.getAttribute('name') || el.getAttribute('placeholder') || el.getAttribute('aria-label') || 'Unknown');
    }

    const results: FieldState[] = [];
    const seen = new Set<Element>();

    for (const shell of Array.from(document.querySelectorAll('.select-shell'))) {
      if (seen.has(shell)) continue;
      seen.add(shell);
      const label = getComboboxLabel(shell);
      if (!label || label.length > 220) continue;
      const display = comboboxDisplay(shell);
      results.push({
        label,
        kind: 'select',
        value: display,
        unfilled: !display,
        required: isRequired(label)
      });
    }

    const controls = document.querySelectorAll(
      'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea'
    );

    for (const el of Array.from(controls)) {
      if (el.closest('.select-shell')) continue;
      if (el instanceof HTMLInputElement && el.classList.contains('select__input')) continue;
      if (el instanceof HTMLInputElement && el.type === 'file') {
        const label = getLabel(el);
        const hasFile = Boolean(el.files?.length);
        results.push({ label, kind: 'file', value: hasFile ? 'attached' : '', unfilled: !hasFile, required: isRequired(label) });
        continue;
      }
      if (el instanceof HTMLInputElement && (el.type === 'radio' || el.type === 'checkbox')) continue;
      if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
        const label = getLabel(el);
        if (/ABOUT THE (TEAM|JOB)/i.test(label)) continue;
        const value = normalize(el.value || '');
        results.push({
          label,
          kind: el instanceof HTMLTextAreaElement ? 'textarea' : 'text',
          value,
          unfilled: !value,
          required: isRequired(label)
        });
      }
    }

    return results;
  });
}

/** Fields we expect filled from profile + screening defaults (not guessing unknown answers). */
const EXPECTED_COMBOBOX_FILLED: Array<{ pattern: RegExp; valuePattern?: RegExp }> = [
  { pattern: /country|^phone$/i, valuePattern: /united states|\+1/i },
  {
    pattern: /clearance eligibility|security clearance.*eligible/i,
    valuePattern: /^no\b|not eligible|do not hold/i
  },
  { pattern: /clearance level have you held/i, valuePattern: /never held|n\/a/i },
  { pattern: /export controls|protected individual/i, valuePattern: /none of the above/i },
  { pattern: /u\.s\. work authorization|authorized to work in the united states/i, valuePattern: /^yes\b/i },
  { pattern: /sponsorship from anduril|require sponsorship|h1b/i, valuePattern: /^yes\b/i },
  { pattern: /history with anduril|previously applied/i, valuePattern: /^no\b/i },
  { pattern: /employed by anduril|company that anduril has acquired/i, valuePattern: /^no\b/i },
  { pattern: /conflict of interest|worked for the us government/i, valuePattern: /^no\b/i },
  { pattern: /how did you hear about anduril/i, valuePattern: /linkedin/i },
  { pattern: /^gender$/i, valuePattern: /male/i },
  { pattern: /hispanic\/latino/i, valuePattern: /^no\b|not hispanic/i },
  { pattern: /veteran status/i, valuePattern: /not a protected veteran/i },
  { pattern: /disability status/i, valuePattern: /no.*disability/i }
];

test.describe('Greenhouse Anduril autofill', () => {
  test('autofill fills all known fields on Anduril apply form', async ({ context }) => {
    test.setTimeout(120_000);

    const issues: ConsoleIssue[] = [];
    const page = await context.newPage();
    attachConsoleCollector(page, issues);
    page.on('console', (msg) => {
      const text = msg.text();
      if (text.includes('[JobFill]') || text.includes('fillLabeledComboboxes')) {
        console.log(`[BROWSER] ${text}`);
      }
    });

    const worker = context.serviceWorkers()[0] ?? (await context.waitForEvent('serviceworker'));
    await seedAutofillProfile(worker, testProfile);

    await page.goto(ANDURIL_URL);
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(3000);

    for (const frame of page.frames()) {
      const count = await frame.locator('.select-shell').count();
      if (count > 0) console.log(`Frame ${frame.url().slice(0, 80)}: ${count} select-shells`);
    }

    const before = await collectGreenhouseFieldStates(page);
    const shellCountBefore = await page.locator('.select-shell').count();
    console.log(
      `Before autofill: ${before.filter((f) => f.unfilled).length} unfilled / ${before.length} total, ${shellCountBefore} select-shells`
    );

    const floatingBtn = page.locator('#jobfill-floating-button');
    await expect(floatingBtn).toBeVisible({ timeout: 20_000 });
    await floatingBtn.click();

    await page.waitForTimeout(100_000);

    const after = await collectGreenhouseFieldStates(page);
    const comboboxes = after.filter((f) => f.kind === 'select');
    const unfilledComboboxes = comboboxes.filter((f) => f.unfilled);
    const requiredUnfilled = after.filter((f) => f.unfilled && f.required);

    const missingExpected = EXPECTED_COMBOBOX_FILLED.flatMap(({ pattern, valuePattern }) => {
      const match = comboboxes.find((c) => pattern.test(c.label));
      if (!match) return [`No combobox found matching ${pattern}`];
      if (match.unfilled) return [`Unfilled: ${match.label}`];
      if (valuePattern && !valuePattern.test(match.value)) {
        return [`Wrong value for ${match.label}: got "${match.value}"`];
      }
      return [];
    });

    const report = {
      url: ANDURIL_URL,
      timestamp: new Date().toISOString(),
      profile: testProfile,
      comboboxes,
      unfilledComboboxes,
      requiredUnfilled,
      missingExpected,
      textFields: after.filter((f) => f.kind === 'text'),
      consoleWarnings: issues.filter((i) => i.type === 'warning').slice(-20)
    };

    fs.mkdirSync(path.dirname(REPORT_PATH), { recursive: true });
    fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2));
    console.log(`Report: ${REPORT_PATH}`);
    console.log('Comboboxes:', JSON.stringify(comboboxes, null, 2));
    console.log('Missing expected:', missingExpected);

    await expect(page.locator('input').filter({ has: page.locator('[value="Akshay"]') }).first()).toBeTruthy();
    await expect(page.getByLabel(/first name/i)).toHaveValue('Akshay');
    await expect(page.getByLabel(/last name/i)).toHaveValue('Borse');
    await expect(page.getByLabel(/^email/i)).toHaveValue('amsborse@gmail.com');

    expect(
      missingExpected,
      `Expected comboboxes not filled:\n${missingExpected.join('\n')}\nSee ${REPORT_PATH}`
    ).toEqual([]);

    expect(
      requiredUnfilled.filter((f) => !/cover letter|if other, please specify/i.test(f.label)),
      `Required fields empty:\n${requiredUnfilled.map((f) => f.label).join('\n')}`
    ).toEqual([]);

    await page.close();
  });
});
