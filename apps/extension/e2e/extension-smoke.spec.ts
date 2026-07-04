import {
  test,
  expect,
  attachConsoleCollector,
  assertNoCriticalIssues,
  getExtensionId,
  type ConsoleIssue
} from './extension.fixture';

const FIXTURE_URL = 'http://127.0.0.1:8765/test-application.html';

const testProfile = {
  firstName: 'Jane',
  lastName: 'Doe',
  fullName: 'Jane Doe',
  email: 'jane.doe@example.com',
  phone: '+1 (555) 123-4567',
  location: 'San Francisco, CA',
  linkedin: 'https://linkedin.com/in/janedoe',
  github: 'https://github.com/janedoe',
  portfolio: 'https://janedoe.dev',
  workAuthorization: 'Yes',
  sponsorship: 'No',
  yearsExperience: '5',
  currentTitle: 'Software Engineer',
  targetRole: 'Senior Engineer',
  salaryExpectations: '$140,000'
};

test.describe('JobFill extension smoke', () => {
  test('popup loads without console errors', async ({ context, extensionId }) => {
    const issues: ConsoleIssue[] = [];
    const page = await context.newPage();
    attachConsoleCollector(page, issues);

    await page.goto(`chrome-extension://${extensionId}/popup.html`);
    await expect(page.locator('#btn-autofill')).toBeVisible({ timeout: 10_000 });

    await page.waitForTimeout(1500);
    assertNoCriticalIssues(issues, true);
    await page.close();
  });

  test('dashboard profile editor loads and accepts input', async ({ context, extensionId }) => {
    const issues: ConsoleIssue[] = [];
    const page = await context.newPage();
    attachConsoleCollector(page, issues);

    await page.goto(`chrome-extension://${extensionId}/dashboard.html#profile`);
    await expect(page.getByRole('heading', { name: 'User Profile' })).toBeVisible({ timeout: 15_000 });

    const firstName = page.locator('#firstName');
    await expect(firstName).toBeVisible();
    await firstName.fill('Akshay');
    await expect(firstName).toHaveValue('Akshay');

    await page.getByRole('button', { name: /save profile settings/i }).click();
    await expect(page.getByText(/synchronized successfully|saved locally/i)).toBeVisible({ timeout: 10_000 });

    assertNoCriticalIssues(issues, true);
    await page.close();
  });

  test('background scan + autofill on fixture form', async ({ context }) => {
    const issues: ConsoleIssue[] = [];
    const jobPage = await context.newPage();
    attachConsoleCollector(jobPage, issues);

    await jobPage.goto(FIXTURE_URL);
    await jobPage.waitForLoadState('networkidle');
    await jobPage.waitForTimeout(1500);

    const worker = context.serviceWorkers()[0] ?? (await context.waitForEvent('serviceworker'));
    const tabId = await worker.evaluate(async (url) => {
      const tabs = await chrome.tabs.query({ url: `${url}*` });
      return tabs[0]?.id ?? null;
    }, FIXTURE_URL);

    expect(tabId, 'fixture tab should be discoverable by the extension').not.toBeNull();

    const scanResult = await worker.evaluate(
      async ({ tabId: id, profile }) => {
        return new Promise<{
          success?: boolean;
          fields?: { id: string; proposedValue?: string }[];
          error?: string;
        }>((resolve) => {
          chrome.tabs.sendMessage(id, { action: 'scan', profile }, (response) => {
            if (chrome.runtime.lastError) {
              resolve({ error: chrome.runtime.lastError.message });
              return;
            }
            resolve(response ?? { error: 'empty response' });
          });
        });
      },
      { tabId, profile: testProfile }
    );

    expect(scanResult.error, `scan failed: ${scanResult.error}`).toBeUndefined();
    expect(scanResult.success).toBe(true);
    expect(scanResult.fields?.length).toBeGreaterThan(0);

    const approvedFields = (scanResult.fields ?? [])
      .filter((f) => f.proposedValue && f.proposedValue !== '[Resume Default]')
      .map((f) => ({ id: f.id, proposedValue: f.proposedValue! }));

    const autofillResult = await worker.evaluate(
      async ({ tabId: id, fields, profile }) => {
        return new Promise<{ success?: boolean; filledCount?: number; error?: string }>((resolve) => {
          chrome.tabs.sendMessage(id, { action: 'autofill', fields, profile }, (response) => {
            if (chrome.runtime.lastError) {
              resolve({ error: chrome.runtime.lastError.message });
              return;
            }
            resolve(response ?? { error: 'empty response' });
          });
        });
      },
      { tabId, fields: approvedFields, profile: testProfile }
    );

    expect(autofillResult.error, `autofill failed: ${autofillResult.error}`).toBeUndefined();
    expect(autofillResult.success).toBe(true);
    expect(autofillResult.filledCount).toBeGreaterThan(0);

    await expect(jobPage.locator('#email')).toHaveValue('jane.doe@example.com');
    await expect(jobPage.locator('#first_name')).toHaveValue('Jane');

    assertNoCriticalIssues(issues, true);
    await jobPage.close();
  });

  test('Rippling styled dropdowns autofill', async ({ context }) => {
    const page = await context.newPage();
    page.on('console', msg => {
      console.log(`[BROWSER CONSOLE] [${msg.type()}] ${msg.text()}`);
    });
    const targetUrl = 'https://ats.rippling.com/rippling/jobs/1f81bd71-a3b5-4b91-aa6c-9999417a4c47/apply?jobSite=LinkedIn&jobBoardSlug=rippling&jobId=1f81bd71-a3b5-4b91-aa6c-9999417a4c47&step=application';
    
    await page.goto(targetUrl);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2000);

    // Locate the floating button
    const floatingBtn = page.locator('#jobfill-floating-button');
    await expect(floatingBtn).toBeVisible({ timeout: 15_000 });

    // Seed profile in chrome.storage.local before click
    const worker = context.serviceWorkers()[0] ?? (await context.waitForEvent('serviceworker'));
    await worker.evaluate(async () => {
      const demoProfile = {
        firstName: "Akshay",
        lastName: "Borse",
        fullName: "Akshay Borse",
        email: "amsborse@gmail.com",
        phone: "+1 4253369852",
        location: "Seattle, WA",
        linkedin: "https://www.linkedin.com/in/amsborse/",
        github: "https://github.com/amsborse",
        portfolio: "https://amsborse.github.io/resume",
        workAuthorization: "Yes",
        sponsorship: "Yes",
        yearsExperience: "7",
        currentTitle: "Senior Software Engineer",
        targetRole: "Senior Software Engineer",
        currentCompany: "Microsoft",
        salaryExpectations: "",
        pronouns: "He/him/his",
        gender: "Male",
        raceEthnicity: "Asian",
        hispanic: "No",
        veteran: "I am not a protected veteran",
        disability: "No, I don't have a disability",
        smsConsent: "No - I do not consent to receiving text messages"
      };
      await chrome.storage.local.set({ jobfill_profile: demoProfile });
    });

    // Click the floating button to trigger autofill!
    await floatingBtn.click();

    // Wait for resume parse + dropdown selections to finish
    await page.waitForTimeout(18_000);

    const comboboxNearLabel = async (labelText: string) => {
      return page.evaluate((label) => {
        const byDataInput =
          label.toLowerCase().includes('pronoun')
            ? (document.querySelector('[data-input="pronouns"]') as HTMLElement | null)
            : null;
        const comboboxes = byDataInput
          ? [byDataInput.closest('[role="combobox"]') || byDataInput]
          : (Array.from(document.querySelectorAll('[role="combobox"]')) as HTMLElement[]);
        for (const combobox of comboboxes) {
          if (!combobox) continue;
          let node: HTMLElement | null = combobox;
          for (let depth = 0; depth < 8 && node; depth++) {
            if (node.textContent?.includes(label)) {
              const input = combobox.querySelector('input') as HTMLInputElement | null;
              const child = combobox.querySelector('p, span');
              return (
                child?.textContent?.replace(/\s+/g, ' ').trim() ||
                input?.value?.trim() ||
                combobox.textContent?.replace(/\s+/g, ' ').trim() ||
                ''
              );
            }
            node = node.parentElement;
          }
        }
        return '';
      }, labelText);
    };

    // Text inputs
    await expect(page.getByRole('textbox', { name: /first name/i })).toHaveValue('Akshay');
    await expect(page.getByRole('textbox', { name: /last name/i })).toHaveValue('Borse');
    await expect(page.getByRole('textbox', { name: /email/i })).toHaveValue('amsborse@gmail.com');
    await expect(page.getByRole('textbox', { name: /phone number/i })).toHaveValue('425-336-9852');
    await expect(page.getByRole('textbox', { name: /linkedin link/i })).toHaveValue(/linkedin\.com\/in\/amsborse\/?$/);
    await expect(page.getByRole('textbox', { name: /website link/i })).toHaveValue('https://amsborse.github.io/resume');

    const pronounVal = await page.evaluate(() => {
      const input =
        (document.querySelector('[data-input="pronouns"]') as HTMLElement | null) ||
        document.getElementById('field-20');
      if (!input) return '';
      const root = input.closest('[role="combobox"]') || input.parentElement;
      const child = root?.querySelector('p, span[class*="single"], [class*="value"]');
      return (
        child?.textContent?.replace(/\s+/g, ' ').trim() ||
        (input as HTMLInputElement).value?.trim() ||
        root?.textContent?.replace(/\s+/g, ' ').trim() ||
        ''
      );
    });

    await expect(async () => {
      const val = await page.evaluate(() => {
        const input =
          (document.querySelector('[data-input="pronouns"]') as HTMLElement | null) ||
          document.getElementById('field-20');
        if (!input) return '';
        const root = input.closest('[role="combobox"]') || input.parentElement;
        const child = root?.querySelector('p, span');
        return child?.textContent?.trim() || (input as HTMLInputElement).value?.trim() || '';
      });
      expect(val).toMatch(/he\/him\/his|him his he/i);
    }).toPass({ timeout: 8_000 });

    const genderVal = await page.locator('#field-63').textContent();
    const raceVal = await page.locator('#field-69').inputValue();
    const hispanicVal = await page.locator('#field-76').textContent();
    const veteranVal = await page.locator('#field-82').textContent();
    const disabilityVal = await page.locator('#field-88').textContent();

    console.log('--- Rippling Autofill E2E Test Results ---');
    console.log('Pronoun filled value:', pronounVal);
    console.log('Gender filled value:', genderVal);
    console.log('Race filled value:', raceVal);
    console.log('Hispanic filled value:', hispanicVal);
    console.log('Veteran filled value:', veteranVal);
    console.log('Disability filled value:', disabilityVal);

    // EEO fields from profile
    expect(pronounVal?.trim()).toMatch(/he\/him\/his|him his he/i);
    expect(genderVal?.trim()).toBe('Male');
    await expect(page.locator('#field-69')).not.toHaveValue('', { timeout: 10_000 });
    const raceValFinal = await page.locator('#field-69').inputValue();
    expect(raceValFinal?.trim()).toBe('Asian');
    expect(hispanicVal?.trim()).toBe('No');
    expect(veteranVal?.trim()).toBe('I am not a protected veteran');
    await expect(page.locator('#field-88')).not.toHaveText(/^Select\.\.\.$/i, { timeout: 10_000 });
    const disabilityValFinal = await page.locator('#field-88').textContent();
    expect(disabilityValFinal?.trim()).toBe("No, I don't have a disability");
    await expect(page.getByRole('radio', { name: /no - i do not consent to receiving text messages/i })).toBeChecked();

    const emptyVisibleInputs = await page.evaluate(() => {
      const inputs = Array.from(
        document.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"])')
      ) as HTMLInputElement[];
      return inputs
        .filter((input) => {
          const rect = input.getBoundingClientRect();
          if (rect.width <= 0 || rect.height <= 0) return false;

          if (input.getAttribute('data-input') === 'select-search-input') {
            const combobox = input.closest('[role="combobox"]');
            const display = combobox?.textContent?.replace(/\s+/g, ' ').trim() || '';
            if (display && !/^(search|select\.\.\.|select)$/i.test(display)) return false;
          }

          const combobox = input.closest('[role="combobox"]');
          if (combobox && input.getAttribute('role') === 'combobox') {
            const display = combobox.textContent?.replace(/\s+/g, ' ').trim() || '';
            if (display && !/^(search|select\.\.\.|select|textbox)$/i.test(display)) return false;
          }

          return !input.value?.trim();
        })
        .map((input) => ({
          id: input.id,
          label: input.getAttribute('aria-labelledby') || input.placeholder || input.name,
          dataInput: input.getAttribute('data-input')
        }));
    });

    console.log('Remaining empty inputs:', JSON.stringify(emptyVisibleInputs, null, 2));
    expect(emptyVisibleInputs, `Unfilled inputs: ${JSON.stringify(emptyVisibleInputs)}`).toEqual([]);

    await page.close();
  });
});
