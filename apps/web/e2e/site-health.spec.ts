import { expect, test } from "@playwright/test";

async function expectStylesLoaded(page: import("@playwright/test").Page) {
  const stylesheetHref = await page.locator('link[rel="stylesheet"]').first().getAttribute("href");
  expect(stylesheetHref, "page should reference a stylesheet").toBeTruthy();

  const cssResponse = await page.request.get(stylesheetHref!);
  expect(cssResponse.status(), `stylesheet should load: ${stylesheetHref}`).toBe(200);
  const css = await cssResponse.text();
  expect(css.length, "compiled CSS should not be empty").toBeGreaterThan(1000);
  expect(css).toContain(".shell");
}

test.describe("CareerOS web health", () => {
  test("landing page loads with styles", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/CareerOS/i);
    await expectStylesLoaded(page);

    const bodyBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(bodyBg).not.toBe("rgba(0, 0, 0, 0)");
  });

  test("app shell renders sidebar layout", async ({ page }) => {
    await page.goto("/profile");
    await expectStylesLoaded(page);

    const shell = page.locator(".shell");
    await expect(shell).toBeVisible();

    const display = await shell.evaluate((el) => getComputedStyle(el).display);
    expect(display).toBe("grid");

    await expect(page.locator(".sidebar")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "CareerOS sections" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Profile", level: 1 })).toBeVisible();
  });

  test("profile page loads seeded profile sections", async ({ page }) => {
    await page.goto("/profile");

    await expect(page.getByRole("heading", { name: "Profile", level: 1 })).toBeVisible();
    await expect(page.locator(".profile-data-card").first()).toBeVisible();
    await expect(page.getByText(/roles saved|No work history saved yet/i)).toBeVisible();
    await expect(page.getByText(/saved answers|No answers saved yet/i)).toBeVisible();
  });

  test("apply-pilot page cards are styled", async ({ page }) => {
    await page.goto("/apply-pilot");
    await expectStylesLoaded(page);

    const card = page.locator(".toc-card").first();
    await expect(card).toBeVisible();

    const borderRadius = await card.evaluate((el) => getComputedStyle(el).borderRadius);
    expect(borderRadius).not.toBe("0px");
  });
});
