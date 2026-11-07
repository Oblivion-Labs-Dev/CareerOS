import { expect, test } from "@playwright/test";

// Since 5c58cc2 the default navigation is core-only: disabled pages (Analytics
// among them) are filtered out unless NEXT_PUBLIC_CAREEROS_NAV=full, so the
// "Disabled pages" toggle no longer renders.
test("default sidebar shows core pages only, with no disabled-pages toggle", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");
  const sidebar = page.locator("#careeros-primary-navigation");
  await expect(sidebar).toBeVisible();
  await expect(sidebar.getByRole("link").first()).toBeVisible();
  await expect(sidebar.getByText("Career workspace", { exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "Analytics", exact: true })).toHaveCount(0);
  await expect(sidebar.getByText("Analytics", { exact: true })).toHaveCount(0);
  await expect(sidebar.getByText("Disabled pages")).toHaveCount(0);
  await expect(sidebar.locator("summary")).toHaveCount(0);
  await page.screenshot({ path: "test-results/sidebar-design.png" });
});
