import { test } from "@playwright/test";

/** Read the match-floor dropdown's options, which should carry the number of
 *  queued jobs each floor reaches. */
test("match floor options show job counts", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/applications", { waitUntil: "domcontentloaded" });
  const select = page.locator("#night-batch-floor");
  await select.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForTimeout(14_000);
  const opts = await select.locator("option").allTextContents();
  console.log("OPTIONS:", opts.map((o) => o.replace(/\s+/g, " ").trim()).join("  |  "));
  await page.locator('[aria-label="Night Batch Center"]').screenshot({ path: "e2e/.artifacts/night-card.png" });
});
