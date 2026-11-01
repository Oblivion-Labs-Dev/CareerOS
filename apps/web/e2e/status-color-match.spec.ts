import { expect, test, type Page } from "@playwright/test";

// Regression: opening a card changed its status colour. Manual Review tags are
// amber but the details panel was purple; Skipped tags are violet but the panel
// was blue. The tag and the opened panel must share a colour family (hue).

/** Hue (0-360) of any CSS colour, or -1 for a grey. */
function hue(page: Page, cssColor: string): Promise<number> {
  return page.evaluate((c) => {
    const probe = document.createElement("span");
    probe.style.color = c;
    document.body.appendChild(probe);
    const [r, g, b] = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g)!.slice(0, 3).map((v) => Number(v) / 255);
    probe.remove();
    const max = Math.max(r, g, b), d = max - Math.min(r, g, b);
    if (d < 0.02) return -1;
    const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return (h * 60 + 360) % 360;
  }, cssColor);
}

for (const status of ["skipped", "manual"]) {
  test(`${status} tag and opened details share a colour @local`, async ({ page }) => {
    await page.goto("/applications");
    const card = page.locator(`[data-status="${status}"]`).first();
    await expect(card).toBeVisible({ timeout: 60_000 });
    const tagColor = await card.locator('[class*="status"] i').first().evaluate((el) => getComputedStyle(el).backgroundColor);

    await card.scrollIntoViewIfNeeded();
    await card.click();
    const panel = page.locator(`[class*="detail"][data-status="${status}"]`).first();
    await expect(panel).toBeAttached({ timeout: 15_000 });
    const panelTone = await panel.evaluate((el) => getComputedStyle(el).getPropertyValue("--tone").trim());

    const tagH = await hue(page, tagColor);
    const panelH = await hue(page, panelTone);
    expect(tagH, "tag should be coloured, not grey").toBeGreaterThanOrEqual(0);
    const diff = Math.min(Math.abs(tagH - panelH), 360 - Math.abs(tagH - panelH));
    expect(diff, `tag hue ${tagH.toFixed(0)} vs panel hue ${panelH.toFixed(0)}`).toBeLessThan(35);
  });
}
