import { test } from "@playwright/test";
test("screenshot the night batch row", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/applications", { waitUntil: "domcontentloaded" });
  const row = page.locator("#night-batch");
  await row.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForTimeout(14_000);
  await row.screenshot({ path: "e2e/.artifacts/batch-row.png" });
  const panel = page.getByLabel("Last update");
  console.log("PANEL:", (await panel.innerText()).replace(/\s+/g, " ").slice(0, 240));
});
