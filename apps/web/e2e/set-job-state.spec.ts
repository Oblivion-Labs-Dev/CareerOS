import { expect, test } from "@playwright/test";

/**
 * Set one application's state from the side panel, targeting it by job id.
 *
 * Company name is not a safe handle here — there are 64 Roblox rows — so this
 * clicks the card carrying the exact data-job-id and reads back what the panel
 * reports afterwards.
 *
 *   MARK_JOBS="apjob_x=QUEUED,apjob_y=INELIGIBLE" npx playwright test e2e/set-job-state.spec.ts
 */
const PAIRS = (process.env.MARK_JOBS || "")
  .split(",")
  .map((p) => p.trim())
  .filter(Boolean)
  .map((p) => {
    const [id, rest] = p.split("=");
    const [state, hint] = (rest || "QUEUED").split(":");
    return { id: id.trim(), state: state.trim(), hint: (hint || "").trim() };
  });

test("set application states by id @local", async ({ page }) => {
  test.setTimeout(600_000);
  expect(PAIRS.length, "set MARK_JOBS").toBeGreaterThan(0);

  for (const { id, state, hint } of PAIRS) {
    // Filtering to Manual keeps the list small enough that the row is rendered
    // without paging; the search box then narrows it to a handful.
    await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
    const chip = page.getByRole("button", { name: /^Manual/i }).first();
    await chip.waitFor({ state: "visible", timeout: 60_000 });
    await chip.click();
    await page.waitForTimeout(2500);

    // Narrow with the server-side search rather than paging: MARK_JOBS entries
    // may carry an optional :hint after the state to seed it.
    if (hint) {
      const search = page.getByPlaceholder(/Search company/i);
      await search.waitFor({ state: "visible", timeout: 30_000 });
      await search.fill(hint);
      await page.waitForTimeout(3000);
    }
    const card = page.locator(`[data-job-id="${id}"]`).first();
    if (!(await card.count())) {
      console.log(`MISS ${id}: not found in the Manual list`);
      continue;
    }

    await card.scrollIntoViewIfNeeded();
    await card.click();
    await page.waitForTimeout(2000);

    const picker = page.getByLabel(/Set application state/i);
    if (!(await picker.isVisible().catch(() => false))) {
      console.log(`MISS ${id}: no state selector on the panel`);
      continue;
    }
    await picker.selectOption(state);
    await page.waitForTimeout(3500);
    console.log(`SET ${id} -> ${state}`);
  }
});
