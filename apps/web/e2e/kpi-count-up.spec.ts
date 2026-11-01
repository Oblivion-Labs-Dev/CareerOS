import { expect, test } from "@playwright/test";

// Dashboard KPIs climb from 0 to the real figure on load. Regression: the
// first render after data arrived showed the final value for a frame, then
// snapped to 0 and counted up again (useCountUp returned its stale null state).
test("Total submitted counts up from 0 without flashing the final value @local", async ({ page }) => {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __kpiSeen: string[] }).__kpiSeen = seen;
    const record = () => {
      const card = document.querySelector('[role="button"][aria-label^="Total submitted"]');
      const text = card?.querySelector('[class*="number"]')?.textContent?.trim();
      if (text && /\d/.test(text) && seen[seen.length - 1] !== text) seen.push(text);
    };
    new MutationObserver(record).observe(document, { subtree: true, childList: true, characterData: true });
  });

  await page.goto("/applications");
  const card = page.getByRole("button", { name: /^Total submitted: \d/ });
  await expect(card).toBeVisible({ timeout: 30_000 });
  const finalValue = (await card.getAttribute("aria-label"))!.match(/^Total submitted: (\d+)/)![1];
  await expect.poll(() => page.evaluate(() => (window as unknown as { __kpiSeen: string[] }).__kpiSeen.at(-1)), { timeout: 5_000 }).toBe(finalValue);

  const seen = await page.evaluate(() => (window as unknown as { __kpiSeen: string[] }).__kpiSeen);
  expect(seen[0]).toBe("0");
  if (Number(finalValue) > 0) {
    expect(seen.length).toBeGreaterThan(2); // intermediate values, not a jump
    expect(seen.slice(0, -1)).not.toContain(finalValue);
  }
});
