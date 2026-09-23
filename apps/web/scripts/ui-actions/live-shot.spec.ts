import { test } from "@playwright/test";

/** Screenshot the Night Batch card while a run is in flight, without reloading,
 *  to confirm the card is the live surface for the batch. */
test("capture the live night batch card", async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto("/applications", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(20_000);
  for (let i = 1; i <= 3; i += 1) {
    await page.screenshot({ path: `e2e/.artifacts/live-card-${i}.png` });
    const card = page.getByLabel("Night Batch Center");
    const txt = await card.innerText().catch(() => "");
    console.log(`--- ${i} ---`, txt.replace(/\s+/g, " ").slice(0, 400));
    await page.waitForTimeout(40_000);
  }
});
