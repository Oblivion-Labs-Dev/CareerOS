import { defineConfig } from "@playwright/test";
// Browser API calls are intercepted by the fixture: no backend or real applications.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "application-grid.spec.ts",
  workers: 1,
  timeout: 120000,
  reporter: "list",
  use: {
    browserName: "firefox",
    baseURL: "http://127.0.0.1:5057",
    screenshot: "only-on-failure",
    // Valid at runtime (BrowserContextOptions) but missing from this
    // Playwright version's PlaywrightTestOptions type.
    // @ts-expect-error — reducedMotion
    reducedMotion: "reduce",
  },
  webServer: {
    command: "node e2e/grid-preview.cjs",
    url: "http://127.0.0.1:5057/login",
    timeout: 120000,
    reuseExistingServer: false,
    env: { CAREER_OS_API_PUBLIC_URL: "http://127.0.0.1:58499" },
  },
});
