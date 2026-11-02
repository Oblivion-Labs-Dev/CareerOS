import { test } from "@playwright/test";

test("screenshot the add-jobs-by-url panel", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
  const toggle = page.getByRole("button", { name: /Add jobs? by URL/i }).first();
  await toggle.waitFor({ state: "visible", timeout: 60_000 });
  await toggle.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/.artifacts/quickadd-collapsed.png" });
  await toggle.click();
  await page.waitForTimeout(1200);
  await toggle.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/.artifacts/quickadd-open.png" });
});
