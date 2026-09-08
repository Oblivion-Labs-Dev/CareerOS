import { defineConfig, devices } from "@playwright/test";

// `pnpm dev` binds port 5000, so default here rather than to Playwright's 3000 —
// otherwise `reuseExistingServer` never recognises the running dev server and
// every run tries to boot a duplicate that dies with EADDRINUSE.
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:5000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    // Logs in once (no-op when the instance has no password configured) so page
    // tests aren't all bounced to /login by the auth gate.
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      // Firefox by default: this dev machine runs a large local model plus the
      // dev stack, and Chromium's process-per-tab model was the difference
      // between a suite that runs and one that gets OOM-killed mid-test.
      // Override with PLAYWRIGHT_BROWSER=chromium when a Chromium-specific
      // behaviour actually needs verifying.
      name: process.env.PLAYWRIGHT_BROWSER || "firefox",
      use: {
        ...(process.env.PLAYWRIGHT_BROWSER === "chromium"
          ? devices["Desktop Chrome"]
          : devices["Desktop Firefox"]),
        storageState: "./e2e/.auth/session.json",
      },
      dependencies: ["setup"],
    },
  ],
  webServer: process.env.CI
    ? undefined
    : {
        command: "pnpm dev",
        url: BASE_URL,
        reuseExistingServer: true,
        timeout: 120_000,
      },
});
