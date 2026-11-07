import { expect, test } from "@playwright/test";

/** Dashboard tile values were hard-coded white, so in light mode they vanished
 *  on the cream cards. Every API call is a local fixture. */
for (const atmosphere of ["standard", "cinematic"]) {
  test(`dashboard tile values are readable in light mode (${atmosphere})`, async ({ page, baseURL }) => {
    await page.context().addCookies([{ name: "co_session", value: "isolated-ui-fixture", url: baseURL! }]);
    await page.addInitScript((a) => {
      localStorage.setItem("theme", "light");
      localStorage.setItem("careeros.atmosphere", a);
    }, atmosphere);
    await page.route("**/api/**", async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith("/auth/status")) return route.fulfill({ json: { authRequired: false } });
      return route.fulfill({ json: { success: true, state: { status: "IDLE", workers: [] }, jobs: [], items: [], events: [], settings: {}, profile: {}, preferences: {}, total: 0, hasMore: false, statusCounts: {} } });
    });

    await page.goto("/dashboard");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    const value = page.getByText("Gated", { exact: true });
    await expect(value).toBeVisible();
    const color = await value.evaluate((el) => getComputedStyle(el).color);
    const [r, g, b] = color.match(/\d+/g)!.map(Number);
    // Relative luminance well below the cream card behind it.
    expect(0.2126 * r + 0.7152 * g + 0.0722 * b).toBeLessThan(110);
  });
}
