import { expect, test } from "@playwright/test";

test("sidebar groups disabled pages and blocks Auto Apply", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");
  const sidebar = page.locator("#careeros-primary-navigation");
  await expect(sidebar.getByText("Career workspace", { exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "Auto Apply", exact: true })).toHaveCount(0);
  await expect(sidebar.getByText("Auto Apply", { exact: true })).not.toBeVisible();
  await sidebar.locator("summary").click();
  await expect(sidebar.getByText("Auto Apply", { exact: true })).toBeVisible();
  await expect(sidebar.getByText("Analytics", { exact: true })).toBeVisible();
  await sidebar.locator("summary").click();
  await page.screenshot({ path: "test-results/sidebar-design.png" });
  await page.goto("/intelligence/auto-apply");
  await expect(page.getByRole("heading", { name: "Auto Apply is disabled" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Autopilot", exact: false })).toBeVisible();
});
