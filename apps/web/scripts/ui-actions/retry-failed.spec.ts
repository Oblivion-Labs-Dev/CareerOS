import { expect, test } from "@playwright/test";

/**
 * Retries specific FAILED applications using the same "Retry" control a person
 * would click, so a classification or form-filling fix can be verified against
 * the exact jobs that exposed it.
 *
 *   RETRY_COMPANIES="Hiya,Whatnot" npx playwright test -c playwright.actions.config.ts retry-failed
 *
 * Note: never wait for networkidle on this page. The Autopilot view holds an
 * SSE stream open and polls on a timer, so it is never network-idle and the
 * wait silently consumes the entire test timeout.
 */

const COMPANIES = (process.env.RETRY_COMPANIES || "")
  .split(",")
  .map((c) => c.trim())
  .filter(Boolean);

test("retry specific failed applications from the UI", async ({ page }) => {
  test.setTimeout(240_000);
  expect(COMPANIES.length, "set RETRY_COMPANIES").toBeGreaterThan(0);

  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });

  const failedFilter = page.getByRole("button", { name: /^Failed\s/i }).first();
  await failedFilter.waitFor({ state: "visible", timeout: 60_000 });
  await failedFilter.click();
  await page.waitForTimeout(2000);

  for (const company of COMPANIES) {
    // Re-apply the filter each time: clicking Retry refreshes the list and
    // drops back to the default view, so a filter set once does not survive
    // the first retry.
    await page.reload({ waitUntil: "domcontentloaded" });
    const filter = page.getByRole("button", { name: /^Failed\s/i }).first();
    await filter.waitFor({ state: "visible", timeout: 60_000 });
    await filter.click();
    await page.waitForTimeout(2000);

    const search = page.getByPlaceholder(/Search company/i);
    await search.waitFor({ state: "visible", timeout: 30_000 });
    await search.fill(company);
    await page.waitForTimeout(2500);

    const cards = page.getByRole("button", { name: /^Retry/i });
    const count = await cards.count();
    console.log(`[${company}] retry controls visible: ${count}`);
    if (count === 0) {
      await page.screenshot({ path: `e2e/.artifacts/no-retry-${company}.png` });
      continue;
    }
    await cards.first().click();
    console.log(`[${company}] clicked Retry`);
    await page.waitForTimeout(3000);
  }

  await page.screenshot({ path: "e2e/.artifacts/after-retries.png" });
});
