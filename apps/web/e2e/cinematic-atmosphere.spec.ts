import { expect, test } from "@playwright/test";

/** Every API call is a local fixture; nothing reaches a real backend. */
test("cinematic atmosphere is the default, can be disabled, and respects reduced motion", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "co_session", value: "isolated-ui-fixture", url: baseURL! }]);
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/status")) return route.fulfill({ json: { authRequired: false } });
    return route.fulfill({ json: { success: true, state: { status: "IDLE", workers: [] }, jobs: [], items: [], events: [], settings: {}, profile: {}, preferences: {}, total: 0, hasMore: false, statusCounts: {} } });
  });

  await page.goto("/applications?tab=applications");
  await expect(page.locator("html")).toHaveAttribute("data-atmosphere", "cinematic");
  await expect(page.locator(".cinematic-backdrop")).toBeVisible();
  // The layer must not move page elements: the main column stays on screen
  // beside the sidebar and the skip link stays hidden until focused.
  await expect(page.locator("#main-content")).toBeInViewport();
  await expect(page.locator(".skip-link")).not.toBeInViewport();

  const toggle = page.getByRole("button", { name: "Cinematic atmosphere" });
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await toggle.click();
  await expect(page.locator("html")).toHaveAttribute("data-atmosphere", "standard");
  await expect(page.locator(".cinematic-backdrop")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-atmosphere", "standard");
  await expect(page.locator(".cinematic-backdrop")).toHaveCount(0);

  await page.evaluate(() => localStorage.setItem("careeros.atmosphere", "cinematic"));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(page.locator(".cinematic-backdrop")).toBeVisible();
  await expect(page.locator(".career-thread-light")).toHaveCSS("animation-name", "none");
});

test("cinematic light mode lets the backdrop show through the layout wrappers", async ({ page, baseURL }) => {
  await page.context().addCookies([{ name: "co_session", value: "isolated-ui-fixture", url: baseURL! }]);
  await page.addInitScript(() => localStorage.setItem("theme", "light"));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/auth/status")) return route.fulfill({ json: { authRequired: false } });
    return route.fulfill({ json: { success: true, state: { status: "IDLE", workers: [] }, jobs: [], items: [], events: [], settings: {}, profile: {}, preferences: {}, total: 0, hasMore: false, statusCounts: {} } });
  });

  await page.goto("/applications?tab=applications");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator(".cinematic-backdrop")).toBeVisible();
  // The light theme paints these wrappers opaque; over the cinematic backdrop
  // that hid the scene completely.
  for (const selector of [".app-stage", ".main", ".page-content"]) {
    await expect(page.locator(selector).first()).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  }
});
