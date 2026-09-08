import { test } from "@playwright/test";

/**
 * Visual QA sweep. Not an assertion suite — it drives Firefox across every major
 * surface at desktop and mobile widths and writes screenshots outside the repo
 * so the design pass can be reviewed. Skipped unless VISUAL_QA=1 so it never
 * slows the real e2e run.
 */
const OUT = process.env.VISUAL_QA_OUT ?? "";

test.skip(process.env.VISUAL_QA !== "1", "set VISUAL_QA=1 to capture screenshots");

const PAGES: Array<[name: string, path: string]> = [
  ["dashboard", "/dashboard"],
  ["autopilot", "/applications"],
  ["applications", "/applications?tab=applications"],
  ["tracker", "/applications?tab=tracker"],
  ["discover", "/jobs/discover"],
  ["profile", "/profile"],
  ["resumes", "/resumes"],
  ["outreach", "/apply/outreach"],
  ["settings", "/settings"],
];

for (const [name, path] of PAGES) {
  test(`desktop ${name}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `${OUT}/desktop-${name}.png` });
  });
}

for (const [name, path] of PAGES.slice(0, 6)) {
  test(`mobile ${name}`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(path, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: `${OUT}/mobile-${name}.png` });
  });
}

test("light theme dashboard", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.addInitScript(() => window.localStorage.setItem("theme", "light"));
  await page.goto("/dashboard", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/light-dashboard.png` });
});
