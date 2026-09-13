import { expect, test } from "@playwright/test";

/** Run the "Resolve aggregator links" maintenance action from the Applications
 *  overflow menu and report what it changed. */
test("resolve aggregator links from the UI", async ({ page }) => {
  test.setTimeout(400_000);
  page.on("response", (r) => {
    if (r.url().includes("resolve-aggregator-urls")) console.log("NET", r.status());
  });

  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
  const menu = page.getByRole("button", { name: /More actions/i }).first();
  await menu.waitFor({ state: "visible", timeout: 60_000 });
  await menu.click();
  await page.waitForTimeout(800);

  const action = page.getByRole("button", { name: /Resolve aggregator links/i }).first();
  await action.waitFor({ state: "visible", timeout: 20_000 });
  await action.click();

  const note = page.locator('[class*="empty"]').filter({ hasText: /Resolved|aggregator|could not/i }).first();
  await note.waitFor({ state: "visible", timeout: 300_000 });
  console.log("RESULT:", (await note.innerText()).replace(/\s+/g, " ").slice(0, 240));
  await page.screenshot({ path: "e2e/.artifacts/aggregator-resolved.png" });
});
