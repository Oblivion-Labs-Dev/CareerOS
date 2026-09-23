import { defineConfig, devices } from "@playwright/test";

/**
 * One-off UI actions, not tests: each drives the running CareerOS app against
 * the real database to do a job a person would otherwise click through
 * (mark an application's state, retry failed ones, stop the batch, run a
 * maintenance action, take a screenshot). They live outside e2e/ so that
 * `playwright test` never runs them by accident. Several change real
 * application data. Run one deliberately, by name:
 *
 *   MARK_COMPANY=Acme npx playwright test -c playwright.actions.config.ts mark-submitted
 *
 * Logs in with the same setup step as the e2e suite (see e2e/auth.setup.ts).
 */
const BASE_URL = process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:5000";

export default defineConfig({
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: BASE_URL,
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testDir: "./e2e", testMatch: /auth\.setup\.ts/ },
    {
      name: "actions",
      testDir: "./scripts/ui-actions",
      use: {
        ...devices["Desktop Firefox"],
        storageState: "./e2e/.auth/session.json",
      },
      dependencies: ["setup"],
    },
  ],
});
