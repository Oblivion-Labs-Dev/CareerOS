import { expect, test } from "@playwright/test";

for (const width of [390, 1440]) {
  test(`workspace illustrations remain readable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of ["/applications", "/jobs/discover", "/profile", "/settings"]) {
      await page.goto(route);
      await expect(page.locator("main h1")).toBeVisible();
      await expect(page.locator("main [data-kind] svg").first()).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`${route.replaceAll("/", "-")}.png`) });
    }
  });
}

test("motion can be paused across navigation without hiding content", async ({ page }) => {
  await page.goto("/settings");
  await page.getByRole("button", { name: "Pause page animations", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "paused");
  await page.goto("/profile");
  await expect(page.getByRole("button", { name: "Resume page animations", exact: true })).toBeVisible();
  await expect(page.locator("main h1")).toBeVisible();
  const animations = await page.locator("main [data-kind] svg *").evaluateAll(elements => elements.map(element => getComputedStyle(element).animationName));
  expect(animations.every(name => name === "none")).toBe(true);
  await page.getByRole("button", { name: "Resume page animations", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "on");
});

test("page illustrations respect reduced motion", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/settings");
  await expect(page.locator("main [data-kind] svg")).toBeVisible();
  const animations = await page.locator("main [data-kind] svg *").evaluateAll(elements => elements.map(element => getComputedStyle(element).animationName));
  expect(animations.every(name => name === "none")).toBe(true);
});
