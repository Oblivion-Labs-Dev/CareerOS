import { expect, test } from "@playwright/test";

/** Stop the running batch using the card's own Stop control. */
test("stop the running night batch @local", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/applications", { waitUntil: "domcontentloaded" });
  const stop = page.getByRole("button", { name: /^Stop/i }).first();
  await stop.waitFor({ state: "visible", timeout: 60_000 });
  await stop.click();
  await page.waitForTimeout(6000);
  console.log("clicked Stop");
});
