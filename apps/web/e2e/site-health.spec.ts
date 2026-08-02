import { expect, test } from "@playwright/test";

async function expectStylesLoaded(page: import("@playwright/test").Page) {
  const stylesheetHrefs = await page.locator('link[rel="stylesheet"]').evaluateAll((links) =>
    links
      .map((link) => link.getAttribute("href"))
      .filter((href): href is string => Boolean(href)),
  );
  expect(stylesheetHrefs.length, "page should reference a stylesheet").toBeGreaterThan(0);

  let compiledCssLength = 0;
  for (const stylesheetHref of new Set(stylesheetHrefs)) {
    const cssResponse = await page.request.get(stylesheetHref);
    expect(cssResponse.status(), `stylesheet should load: ${stylesheetHref}`).toBe(200);
    compiledCssLength += (await cssResponse.text()).length;
  }

  expect(compiledCssLength, "compiled CSS should not be empty").toBeGreaterThan(1000);
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

  test("hydrates the connected workspace from cached data without a mismatch", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.addInitScript(() => {
      window.localStorage.setItem("career-os:workspace:snapshot", JSON.stringify({
        profile: { targetRole: "Cached role" },
        discoverTotal: 42,
        discoverStrongMatches: 7,
        applicationsCount: 3,
        profileCompleteness: 50,
        loadedAt: "2026-01-01T00:00:00.000Z",
      }));
    });

    await page.goto("/jobs/discover");
    await expect(page.getByRole("region", { name: "Connected pages" })).toBeVisible();
    expect(consoleErrors.filter((message) => message.includes("Hydration failed"))).toEqual([]);
  });

  test("apply outreach page shows recruiter campaign dashboard", async ({ page }) => {
    await page.goto("/apply/outreach");
    await expectStylesLoaded(page);

    await expect(page.getByRole("heading", { name: "Recruiter email campaigns", level: 1 })).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Delivery metrics" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Refresh" }),
    ).toBeVisible();
  });

  test("apply-pilot page includes email sender outreach section", async ({ page }) => {
    await page.goto("/apply-pilot");
    await expectStylesLoaded(page);

    await expect(page.getByRole("heading", { name: "Gmail sender", level: 2 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Send email", level: 2 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Send email" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Email Outreach" })).toBeVisible();
  });
});
