import { expect, test } from "@playwright/test";

/**
 * State, through the Profile page, that the candidate requires sponsorship.
 *
 * The Save button only enables when the form is dirty, so when the flat field
 * already reads "Yes" a plain re-save is a no-op and the normaliser never runs
 * over the stale saved screening answer that outranks it. Hence the deliberate
 * toggle: write the opposite value, save, then write the true value and save.
 * Nothing may be running a batch while this executes.
 */
test("state that sponsorship is required, via the Profile page @local", async ({ page }) => {
  test.setTimeout(240_000);

  await page.goto("/profile", { waitUntil: "domcontentloaded" });

  const field = page.getByLabel(/will you require sponsorship/i);
  await field.waitFor({ state: "visible", timeout: 60_000 });
  const save = page.getByRole("button", { name: /save application details/i }).first();

  for (const value of ["No", "Yes"]) {
    await field.fill(value);
    await expect(save).toBeEnabled({ timeout: 20_000 });
    await save.click();
    await expect(save).toBeDisabled({ timeout: 30_000 });
    console.log(`saved sponsorship = ${value}`);
  }

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByLabel(/will you require sponsorship/i)).toHaveValue(/yes/i, { timeout: 30_000 });
  await page.screenshot({ path: "e2e/.artifacts/profile-sponsorship.png" });
});
