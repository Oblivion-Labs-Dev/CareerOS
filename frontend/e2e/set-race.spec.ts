import { expect, test } from "@playwright/test";

/** Record the candidate's specific self-identification on the profile, so EEO
 *  questions resolve to an exact option instead of being declined. */
test("set race/ethnicity to South Asian via the Profile page", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/profile", { waitUntil: "domcontentloaded" });

  const field = page.getByLabel(/Race \/ ethnicity/i);
  await field.waitFor({ state: "visible", timeout: 60_000 });
  const save = page.getByRole("button", { name: /save application details/i }).first();

  await field.fill("South Asian");
  await expect(save).toBeEnabled({ timeout: 20_000 });
  await save.click();
  await expect(save).toBeDisabled({ timeout: 30_000 });

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByLabel(/Race \/ ethnicity/i)).toHaveValue(/south asian/i, { timeout: 30_000 });
  console.log("saved raceEthnicity = South Asian");
});
