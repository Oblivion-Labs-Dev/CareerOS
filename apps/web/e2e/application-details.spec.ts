import { expect, test } from "@playwright/test";

test("application dossier renders and closes across statuses", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  for (const status of ["submitted", "skipped", "ineligible"]) {
    await page.goto("/applications?tab=applications");
    await page.getByRole("button", { name: new RegExp(`^${status} \\d`, "i") }).click();
    const card = page.locator(`article[data-status="${status}"]`).first();
    await expect(card).toBeVisible({ timeout: 20000 });
    // Assert against the token, not a literal. This previously hardcoded
    // #249d7a, went stale the moment the palette moved, and stayed red for
    // months while telling us nothing. What actually matters is that a
    // submitted card is drawn in the success role and not in the action
    // colour — success and --accent used to resolve to the same teal, which
    // made "submitted" and "clickable" indistinguishable.
    if (status === "submitted") {
      const { state, success, accent } = await card.evaluate((element) => {
        const root = getComputedStyle(document.documentElement);
        return {
          state: getComputedStyle(element).getPropertyValue("--state").trim(),
          success: root.getPropertyValue("--success").trim(),
          accent: root.getPropertyValue("--accent").trim(),
        };
      });
      expect(state, "a submitted card is drawn in the success role").toBe(success);
      expect(state, "success must be its own colour, not the action colour").not.toBe(accent);
    }
    // The whole card opens the dossier — there is no inner View button to aim
    // for, and a submitted card has no action buttons at all (nothing left to
    // apply to, retry or autofill). This waited 60s for a button that the
    // redesign deliberately removed.
    await card.click();
    const panel = page.getByRole("dialog");
    await expect(panel.getByRole("region", { name: "Application summary" })).toBeVisible();
    await panel.getByRole("button", { name: "Documents", exact: true }).click();
    await expect(panel.getByRole("heading", { name: "Application documents" })).toBeVisible();
    await page.screenshot({ path: `test-results/details-${status}.png` });
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expect(panel).toHaveCount(0);
  }
});
