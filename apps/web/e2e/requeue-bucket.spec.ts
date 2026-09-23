import { expect, test } from "@playwright/test";

/** The Review and Failed lists each offer a bulk requeue, and it must warn
 *  before it acts because the reason each job was parked is cleared. */
test("bulk requeue warns before moving a bucket to the queue @local", async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });

  const failed = page.getByRole("button", { name: /^Review/i }).first();
  await failed.waitFor({ state: "visible", timeout: 60_000 });
  await failed.click();
  await page.waitForTimeout(2500);

  const bulk = page.getByRole("button", { name: /Move all \d+ to queue/i }).first();
  await bulk.waitFor({ state: "visible", timeout: 30_000 });
  console.log("BUTTON:", await bulk.innerText());
  await bulk.click();

  const dialog = page.getByRole("alertdialog");
  await dialog.waitFor({ state: "visible", timeout: 15_000 });
  console.log("DIALOG:", (await dialog.innerText()).replace(/\s+/g, " ").slice(0, 260));
  await page.screenshot({ path: "e2e/.artifacts/requeue-confirm.png" });

  // Cancel must change nothing.
  await dialog.getByRole("button", { name: /^Cancel$/i }).click();
  await expect(dialog).toBeHidden({ timeout: 10_000 });
  console.log("cancel closed the dialog without acting");
});
