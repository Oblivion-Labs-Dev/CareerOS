import { chromium } from '@playwright/test';
import path from 'path';
import fs from 'fs';
import os from 'os';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EXTENSION_PATH = path.join(__dirname, '..', 'dist');

async function main() {
  if (!fs.existsSync(path.join(EXTENSION_PATH, 'manifest.json'))) {
    console.error('ERROR: dist/ not found. Run: pnpm build');
    process.exit(1);
  }

  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_PATH, 'manifest.json'), 'utf-8'));
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'jobfill-ext-check-'));

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    args: [
      `--disable-extensions-except=${EXTENSION_PATH}`,
      `--load-extension=${EXTENSION_PATH}`
    ]
  });

  const page = await context.newPage();
  const issues = [];

  page.on('console', (msg) => {
    if (msg.type() === 'error') issues.push(`[console.error] ${msg.text()}`);
  });

  await page.goto('chrome://extensions/');
  await page.waitForTimeout(2500);

  // Try enabling Developer mode (UI varies by Chrome version)
  await page.evaluate(() => {
    const toggle = document.querySelector('#devMode, extensions-manager')?.shadowRoot?.querySelector('#devMode');
    if (toggle && toggle.getAttribute('aria-pressed') !== 'true') toggle.click();
  }).catch(() => {});
  await page.waitForTimeout(500);

  const cardInfo = await page.evaluate(() => {
    const results = [];

    function walkShadow(root) {
      if (!root) return;
      root.querySelectorAll('extensions-item').forEach((item) => {
        const sr = item.shadowRoot;
        if (!sr) return;
        const name = sr.querySelector('#name')?.textContent?.trim() || '';
        const version = sr.querySelector('#version')?.textContent?.trim() || '';
        const id = sr.querySelector('#extension-id')?.textContent?.trim() || '';
        const errorButton = sr.querySelector('#errors-button');
        const hasErrors = !!errorButton && !errorButton.hasAttribute('hidden');
        const enabledToggle = sr.querySelector('cr-toggle');
        const enabled = enabledToggle?.getAttribute('aria-pressed') === 'true';
        if (name) results.push({ name, version, id, hasErrors, enabled, errorTexts: [] });
      });
      root.querySelectorAll('*').forEach((el) => {
        if (el.shadowRoot) walkShadow(el.shadowRoot);
      });
    }

    walkShadow(document);
    return results;
  });

  const jobFill = cardInfo.find((c) => c.name.includes('JobFill') || c.name.includes('Arsenal'));

  console.log('\n=== chrome://extensions/ Report ===\n');
  console.log(`Built dist version: ${manifest.name} v${manifest.version}`);
  console.log(`Extension path:     ${EXTENSION_PATH}\n`);

  if (!jobFill) {
    console.log('STATUS: Extension card NOT FOUND on chrome://extensions/');
    console.log('Cards found:', cardInfo.length ? cardInfo.map((c) => c.name).join(', ') : '(none)');
  } else {
    console.log(`STATUS: Found "${jobFill.name}"`);
    console.log(`  Version:  ${jobFill.version}`);
    console.log(`  ID:       ${jobFill.id}`);
    console.log(`  Enabled:  ${jobFill.enabled}`);
    console.log(`  Errors:   ${jobFill.hasErrors ? 'YES' : 'NONE'}`);

    if (jobFill.errorTexts.length) {
      console.log('  Error details:');
      jobFill.errorTexts.forEach((e) => console.log(`    - ${e}`));
    }

    if (jobFill.hasErrors) {
      const errorsPage = await context.newPage();
      await errorsPage.goto(`chrome://extensions/?errors=${jobFill.id}`);
      await errorsPage.waitForTimeout(1500);
      const errorBody = await errorsPage.evaluate(() => document.body.innerText.slice(0, 4000));
      console.log('\n--- Error log (chrome://extensions/?errors=...) ---\n');
      console.log(errorBody || '(empty)');
      await errorsPage.close();
    }
  }

  if (issues.length) {
    console.log('\n--- Page console errors ---');
    issues.forEach((i) => console.log(i));
  }

  const workers = context.serviceWorkers();
  if (workers.length > 0) {
    const extId = new URL(workers[0].url()).hostname;
    const dash = await context.newPage();
    const dashIssues = [];
    dash.on('pageerror', (e) => dashIssues.push(e.message));
    dash.on('console', (m) => {
      if (m.type() === 'error') dashIssues.push(m.text());
    });
    await dash.goto(`chrome-extension://${extId}/dashboard.html#profile`);
    await dash.waitForTimeout(2000);
    const hasProfile = await dash.getByRole('heading', { name: 'User Profile' }).isVisible().catch(() => false);
    console.log(`\nSmoke: dashboard#profile loads: ${hasProfile ? 'YES' : 'NO'}`);
    if (dashIssues.length) {
      console.log('Smoke console errors:');
      dashIssues.forEach((e) => console.log(`  - ${e}`));
    }
    await dash.close();
  }

  console.log('\n=================================\n');
  await context.close();
  fs.rmSync(userDataDir, { recursive: true, force: true });

  if (jobFill?.hasErrors) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
