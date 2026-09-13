import { test } from "@playwright/test";
test("screenshot the night batch card", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/applications", { waitUntil: "domcontentloaded" });
  const card = page.getByLabel("Night Batch Center");
  await card.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForTimeout(12_000);
  await card.screenshot({ path: "e2e/.artifacts/night-card.png" });
  console.log("CARD:", (await card.innerText()).replace(/\s+/g, " ").slice(0, 300));
});
