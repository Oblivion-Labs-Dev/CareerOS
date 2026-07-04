import { test as base, chromium, type BrowserContext, type Page } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import os from 'os';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const EXTENSION_PATH = path.join(__dirname, '..', 'dist');

export type ConsoleIssue = { type: string; text: string; url?: string };

export async function getExtensionId(context: BrowserContext): Promise<string> {
  const existing = context.serviceWorkers();
  if (existing.length > 0) {
    return new URL(existing[0].url()).hostname;
  }
  const worker = await context.waitForEvent('serviceworker', { timeout: 20_000 });
  return new URL(worker.url()).hostname;
}

export function attachConsoleCollector(page: Page, issues: ConsoleIssue[]) {
  page.on('console', (msg) => {
    const type = msg.type();
    if (type === 'error' || type === 'warning') {
      issues.push({ type, text: msg.text(), url: page.url() });
    }
  });
  page.on('pageerror', (err) => {
    issues.push({ type: 'pageerror', text: err.message, url: page.url() });
  });
}

export function formatIssues(issues: ConsoleIssue[]): string {
  return issues.map((i) => `[${i.type}] ${i.text}${i.url ? ` (${i.url})` : ''}`).join('\n');
}

export function assertNoCriticalIssues(issues: ConsoleIssue[], allowWarnings = false) {
  const critical = issues.filter((i) => {
    if (i.type === 'pageerror') return true;
    if (i.type === 'error') return true;
    if (!allowWarnings && i.type === 'warning') return true;
    return false;
  });
  if (critical.length > 0) {
    throw new Error(`Console issues detected:\n${formatIssues(critical)}`);
  }
}

type ExtensionFixtures = {
  context: BrowserContext;
  extensionId: string;
};

export const test = base.extend<ExtensionFixtures>({
  context: async ({}, use) => {
    if (!fs.existsSync(path.join(EXTENSION_PATH, 'manifest.json'))) {
      throw new Error(`Extension dist not found at ${EXTENSION_PATH}. Run pnpm build first.`);
    }
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'jobfill-pw-'));
    const context = await chromium.launchPersistentContext(userDataDir, {
      headless: false,
      args: [
        `--disable-extensions-except=${EXTENSION_PATH}`,
        `--load-extension=${EXTENSION_PATH}`
      ]
    });
    await use(context);
    await context.close();
    fs.rmSync(userDataDir, { recursive: true, force: true });
  },
  extensionId: async ({ context }, use) => {
    const id = await getExtensionId(context);
    await use(id);
  }
});

export { expect } from '@playwright/test';
