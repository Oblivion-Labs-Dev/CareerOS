import { expect, test } from "@playwright/test";

test("application dossier renders and closes across statuses", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const status of ["submitted", "skipped", "ineligible"]) {
    await page.goto("/applications?tab=applications");
    await page.getByRole("button", { name: new RegExp(`^${status} \\d`, "i") }).click();
    const card = page.locator(`article[data-status="${status}"]`).first();
    await expect(card).toBeVisible({ timeout: 20000 });
    if (status === "submitted") expect(await card.evaluate(element => getComputedStyle(element).getPropertyValue("--state").trim())).toBe("#249d7a");
    await card.locator("button").first().click();
    const panel = page.getByRole("dialog");
    await expect(panel.getByRole("region", { name: "Application summary" })).toBeVisible();
    await panel.getByRole("button", { name: "Documents", exact: true }).click();
    await expect(panel.getByRole("heading", { name: "Application documents" })).toBeVisible();
    await page.screenshot({ path: `test-results/details-${status}.png` });
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expect(panel).toHaveCount(0);
  }
});
