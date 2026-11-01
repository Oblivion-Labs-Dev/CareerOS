import { expect, test } from "@playwright/test";

// Regression: a card came back smaller after its flip dialog closed. The
// dialog's scroll lock (body overflow: hidden) dropped the body scrollbar, so
// the grid widened while the dialog was open, the dialog landed on that wider
// card, and the card then snapped narrower when the scrollbar returned. The
// lock must not move or resize anything underneath it.

// Playwright hides scrollbars in headless Chromium (and headless Firefox's
// take no space), which hides the bug. Keep Chromium's real scrollbars, as a
// Windows desktop browser shows them.
test.use({ browserName: "chromium", launchOptions: { ignoreDefaultArgs: ["--hide-scrollbars"] } });

test("opening the flip dialog leaves the card's size alone @local", async ({ page }) => {
  await page.goto("/applications");
  const card = page.locator('[data-card-variant="lab"]').first();
  await expect(card).toBeVisible({ timeout: 60_000 });
  // The page must actually have a body scrollbar for this to mean anything.
  const gap = await page.evaluate(() => document.body.getBoundingClientRect().width - document.body.clientWidth);
  expect(gap, "body has no scrollbar to lose").toBeGreaterThan(0);

  const before = await card.boundingBox();
  await card.click();
  await expect(page.locator(".aa-flip-dialog[data-state=open]")).toBeVisible();
  const open = await card.boundingBox();
  expect(open?.width).toBeCloseTo(before!.width, 0);
  expect(open?.height).toBeCloseTo(before!.height, 0);
  expect(open?.x).toBeCloseTo(before!.x, 0);

  await page.keyboard.press("Escape");
  await expect(page.locator(".aa-flip-dialog")).toHaveCount(0);
  const after = await card.boundingBox();
  expect(after?.width).toBeCloseTo(before!.width, 0);
});
