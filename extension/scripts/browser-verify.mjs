import { chromium } from '@playwright/test';
import path from 'path';
import fs from 'fs';
import os from 'os';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EXTENSION_PATH = path.join(__dirname, '..', 'dist');
const SCREENSHOT_DIR = path.join(__dirname, '..', 'e2e', 'screenshots');

function collectIssues(page, issues, label) {
  page.on('console', (msg) => {
    const type = msg.type();
    if (type === 'error' || type === 'warning') {
      issues.push({ label, type, text: msg.text(), url: page.url() });
    }
  });
  page.on('pageerror', (err) => {
    issues.push({ label, type: 'pageerror', text: err.message, url: page.url() });
  });
}

async function getExtensionId(context) {
  const existing = context.serviceWorkers();
  if (existing.length > 0) return new URL(existing[0].url()).hostname;
  const worker = await context.waitForEvent('serviceworker', { timeout: 20_000 });
  return new URL(worker.url()).hostname;
}

async function readExtensionCard(page) {
  return page.evaluate(() => {
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
        if (name) results.push({ name, version, id, hasErrors, enabled });
      });
      root.querySelectorAll('*').forEach((el) => {
        if (el.shadowRoot) walkShadow(el.shadowRoot);
      });
    }
    walkShadow(document);
    return results;
  });
}

async function main() {
  if (!fs.existsSync(path.join(EXTENSION_PATH, 'manifest.json'))) {
    console.error('ERROR: dist/ not found. Run: pnpm build');
    process.exit(1);
  }

  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  const manifest = JSON.parse(fs.readFileSync(path.join(EXTENSION_PATH, 'manifest.json'), 'utf-8'));
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'jobfill-verify-'));
  const issues = [];
  const report = { version: manifest.version, screenshots: [], checks: [] };

  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    viewport: { width: 1280, height: 900 },
    args: [
      `--disable-extensions-except=${EXTENSION_PATH}`,
      `--load-extension=${EXTENSION_PATH}`
    ]
  });

  try {
    const extensionId = await getExtensionId(context);

    // 1. Popup
    const popup = await context.newPage();
    collectIssues(popup, issues, 'popup');
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await popup.waitForSelector('#btn-autofill', { timeout: 15_000 });
    await popup.waitForTimeout(2000);
    const versionTag = await popup.locator('.version-tag').textContent();
    const popupShot = path.join(SCREENSHOT_DIR, '01-popup.png');
    await popup.screenshot({ path: popupShot, fullPage: true });
    report.screenshots.push(popupShot);
    report.checks.push({
      name: 'popup loads',
      pass: versionTag?.includes(manifest.version) ?? false,
      detail: `version tag: ${versionTag?.trim()}`
    });
    await popup.close();

    // 2. Dashboard
    const dash = await context.newPage();
    collectIssues(dash, issues, 'dashboard');
    await dash.goto(`chrome-extension://${extensionId}/dashboard.html#profile`);
    await dash.waitForSelector('#firstName', { timeout: 20_000 });
    await dash.waitForTimeout(2000);
    const dashShot = path.join(SCREENSHOT_DIR, '02-dashboard-profile.png');
    await dash.screenshot({ path: dashShot, fullPage: true });
    report.screenshots.push(dashShot);
    const profileVisible = await dash.getByRole('heading', { name: 'User Profile' }).isVisible();
    report.checks.push({ name: 'dashboard profile', pass: profileVisible, detail: profileVisible ? 'User Profile visible' : 'heading missing' });
    await dash.close();

    // 2b. Arsenal Station portal
    const portal = await context.newPage();
    collectIssues(portal, issues, 'portal');
    await portal.goto(`chrome-extension://${extensionId}/portal.html`);
    await portal.waitForSelector('.station-brand h1', { timeout: 15_000 });
    await portal.waitForTimeout(1500);
    const portalShot = path.join(SCREENSHOT_DIR, '02-portal-landing.png');
    await portal.screenshot({ path: portalShot, fullPage: true });
    report.screenshots.push(portalShot);
    const portalTitle = await portal.locator('.station-brand h1').textContent();
    report.checks.push({
      name: 'portal landing',
      pass: portalTitle?.includes('Arsenal Station') ?? false,
      detail: portalTitle?.trim() || 'missing title'
    });
    await portal.close();

    // 3. chrome://extensions
    const extPage = await context.newPage();
    collectIssues(extPage, issues, 'extensions-page');
    await extPage.goto('chrome://extensions/');
    await extPage.waitForTimeout(2500);
    await extPage.evaluate(() => {
      const toggle = document.querySelector('extensions-manager')?.shadowRoot?.querySelector('#devMode');
      if (toggle && toggle.getAttribute('aria-pressed') !== 'true') toggle.click();
    }).catch(() => {});
    await extPage.waitForTimeout(800);
    const extShot = path.join(SCREENSHOT_DIR, '03-chrome-extensions.png');
    await extPage.screenshot({ path: extShot, fullPage: true });
    report.screenshots.push(extShot);
    const cards = await readExtensionCard(extPage);
    const jobFill = cards.find((c) => c.name.includes('JobFill') || c.name.includes('Arsenal'));
    report.checks.push({
      name: 'extension card',
      pass: !!jobFill,
      detail: jobFill ? `${jobFill.name} v${jobFill.version} enabled=${jobFill.enabled}` : 'not found'
    });
    if (jobFill) {
      report.checks.push({
        name: 'correct version on card',
        pass: jobFill.version === manifest.version,
        detail: `card=${jobFill.version} dist=${manifest.version}`
      });
      report.checks.push({
        name: 'no extension errors',
        pass: !jobFill.hasErrors,
        detail: jobFill.hasErrors ? 'errors button visible' : 'clean'
      });
      if (jobFill.hasErrors) {
        const errPage = await context.newPage();
        await errPage.goto(`chrome://extensions/?errors=${jobFill.id}`);
        await errPage.waitForTimeout(2000);
        const errShot = path.join(SCREENSHOT_DIR, '04-extension-errors.png');
        await errPage.screenshot({ path: errShot, fullPage: true });
        report.screenshots.push(errShot);
        const errText = await errPage.evaluate(() => document.body.innerText.slice(0, 5000));
        report.errorLog = errText;
        await errPage.close();
      }
    }
    await extPage.close();

    // 4. Fixture autofill
    const job = await context.newPage();
    collectIssues(job, issues, 'fixture');
    await job.goto('http://127.0.0.1:8765/test-application.html');
    await job.waitForLoadState('networkidle');
    await job.waitForTimeout(1500);
    const fixtureShot = path.join(SCREENSHOT_DIR, '05-fixture-before.png');
    await job.screenshot({ path: fixtureShot, fullPage: true });
    report.screenshots.push(fixtureShot);

    const worker = context.serviceWorkers()[0];
    const tabId = await worker.evaluate(async (url) => {
      const tabs = await chrome.tabs.query({ url: `${url}*` });
      return tabs[0]?.id ?? null;
    }, 'http://127.0.0.1:8765/test-application.html');

    const profile = {
      firstName: 'Jane', lastName: 'Doe', fullName: 'Jane Doe',
      email: 'jane.doe@example.com', phone: '+1 (555) 123-4567'
    };

    const scan = await worker.evaluate(async ({ tabId, profile }) => {
      return new Promise((resolve) => {
        chrome.tabs.sendMessage(tabId, { action: 'scan', profile }, (r) => {
          resolve(chrome.runtime.lastError ? { error: chrome.runtime.lastError.message } : r);
        });
      });
    }, { tabId, profile });

    const fields = (scan.fields ?? []).filter((f) => f.proposedValue).map((f) => ({ id: f.id, proposedValue: f.proposedValue }));
    const fill = await worker.evaluate(async ({ tabId, fields, profile }) => {
      return new Promise((resolve) => {
        chrome.tabs.sendMessage(tabId, { action: 'autofill', fields, profile }, (r) => {
          resolve(chrome.runtime.lastError ? { error: chrome.runtime.lastError.message } : r);
        });
      });
    }, { tabId, fields, profile });

    await job.waitForTimeout(500);
    const afterShot = path.join(SCREENSHOT_DIR, '06-fixture-after-autofill.png');
    await job.screenshot({ path: afterShot, fullPage: true });
    report.screenshots.push(afterShot);

    const emailVal = await job.locator('#email').inputValue();
    report.checks.push({ name: 'scan', pass: scan.success === true, detail: scan.error || `${scan.fields?.length ?? 0} fields` });
    report.checks.push({ name: 'autofill', pass: fill.success === true, detail: fill.error || `${fill.filledCount} filled` });
    report.checks.push({ name: 'email filled', pass: emailVal === 'jane.doe@example.com', detail: emailVal });
    await job.close();

    // Console issues
    const critical = issues.filter((i) => i.type === 'pageerror' || i.type === 'error');
    report.checks.push({
      name: 'no console errors',
      pass: critical.length === 0,
      detail: critical.length ? critical.map((i) => `[${i.label}] ${i.text}`).join(' | ') : 'clean'
    });
    report.consoleIssues = issues;

    const reportPath = path.join(SCREENSHOT_DIR, 'report.json');
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));

    console.log('\n=== Browser Verification Report ===\n');
    console.log(`Extension: ${manifest.name} v${manifest.version}`);
    console.log(`Load path: ${EXTENSION_PATH}\n`);
    for (const c of report.checks) {
      console.log(`${c.pass ? 'PASS' : 'FAIL'}  ${c.name} — ${c.detail}`);
    }
    console.log('\nScreenshots:');
    report.screenshots.forEach((s) => console.log(`  ${s}`));
    if (report.errorLog) {
      console.log('\nExtension error log:\n');
      console.log(report.errorLog.slice(0, 2000));
    }
    if (critical.length) {
      console.log('\nConsole errors:');
      critical.forEach((i) => console.log(`  [${i.label}] ${i.text}`));
    }
    console.log(`\nFull report: ${reportPath}`);
    console.log('===================================\n');

    const allPass = report.checks.every((c) => c.pass);
    process.exit(allPass ? 0 : 1);
  } finally {
    await context.close();
    fs.rmSync(userDataDir, { recursive: true, force: true });
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
