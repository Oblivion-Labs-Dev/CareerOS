import { defineConfig } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const packageRoot = path.dirname(fileURLToPath(import.meta.url));
const apiRoot = path.resolve(packageRoot, '../api');
const fixturesRoot = path.join(packageRoot, 'fixtures');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [['list']],
  webServer: [
    {
      command: 'python -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: true,
      timeout: 60_000,
      cwd: apiRoot,
    },
    {
      command: 'python -m http.server 8765',
      url: 'http://127.0.0.1:8765/test-application.html',
      reuseExistingServer: true,
      timeout: 30_000,
      cwd: fixturesRoot,
    },
  ],
});
