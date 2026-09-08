import { expect, test } from "@playwright/test";

/**
 * Autopilot control center.
 *
 * These assertions deliberately avoid hard-coded counts — the numbers come from
 * real application data and change constantly. What matters is that the page
 * reports *some* real operational state rather than a placeholder, and that
 * every section renders against the live backend.
 *
 * Nothing here starts a run: triggering Autopilot submits real applications to
 * real employers, which is not something a test suite should do as a side
 * effect. We assert the control is present and leave it unclicked.
 */

const KNOWN_STATES = /Running|Recovering|Paused|Idle|Stopped|Offline|Unknown/;

test.describe("Autopilot control center", () => {
  test("renders live operational state and all four sections", async ({ page }) => {
    const failedRequests: string[] = [];
    page.on("requestfailed", (req) => {
      failedRequests.push(`${req.method()} ${req.url()} (${req.failure()?.errorText})`);
    });
    page.on("response", (res) => {
      if (res.status() >= 500) failedRequests.push(`${res.status()} ${res.request().method()} ${res.url()}`);
    });

    await page.goto("/applications");

    await expect(page.getByRole("heading", { name: /Your job search agent/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // The backend-offline banner must not be showing.
    await expect(page.locator(".backend-offline-alert")).not.toBeVisible();

    // Operational status must resolve to a real state, never a hardcoded label.
    await expect(page.getByText(KNOWN_STATES).first()).toBeVisible({ timeout: 20_000 });

    // All four Autopilot sections exist.
    for (const name of ["Overview", "Applications", "Review", "Diagnostics"]) {
      await expect(page.getByRole("button", { name: new RegExp(`^${name}`) })).toBeVisible();
    }

    // Overview surfaces the operational panels.
    await expect(page.getByText("Live Autopilot Activity", { exact: false })).toBeVisible();
    await expect(page.getByText("Total submitted", { exact: false })).toBeVisible();
    await expect(page.getByText("Needs your attention", { exact: false })).toBeVisible();
    await expect(page.getByText("System health", { exact: false })).toBeVisible();

    expect(failedRequests, `unexpected failed requests: ${failedRequests.join(", ")}`).toHaveLength(0);
  });

  test("total submitted metric shows a real number, not a placeholder", async ({ page }) => {
    await page.goto("/applications");
    await expect(page.getByRole("heading", { name: /Your job search agent/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // Find the "Total submitted" metric card and read its value.
    const metric = page.locator("div", { hasText: /^Total submitted$/ }).first();
    await expect(metric).toBeVisible({ timeout: 20_000 });

    // The value renders above the label inside the same card; assert the card
    // eventually holds digits rather than the "—" loading placeholder.
    const card = metric.locator("xpath=..");
    await expect(card).toContainText(/\d/, { timeout: 20_000 });
  });

  test("applications section filters real application data", async ({ page }) => {
    await page.goto("/applications?tab=applications");
    await expect(page.getByRole("heading", { name: /Your job search agent/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // Status filters replaced the old per-status top-level tabs. Each chip
    // renders "<label> <count>", which also distinguishes it from the section
    // tab of the same name (e.g. the Review tab vs the Review filter).
    for (const label of ["All", "Submitted", "Review", "Failed", "Skipped", "Queued"]) {
      await expect(page.getByRole("button", { name: new RegExp(`^${label}\\s+\\d+$`) })).toBeVisible({
        timeout: 20_000,
      });
    }

    // Search control is present for company/role/location filtering.
    await expect(page.getByPlaceholder(/Search company, role, location/i)).toBeVisible();

    // Switching to Submitted keeps the view rendered (cards or an empty state).
    await page.getByRole("button", { name: /^Submitted\s+\d+$/ }).click();
    await expect(page.getByPlaceholder(/Search company, role, location/i)).toBeVisible();
  });

  test("review section renders its workflow or an honest empty state", async ({ page }) => {
    await page.goto("/applications?tab=review");
    await expect(page.getByRole("heading", { name: /Your job search agent/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // Either staged applications are listed, or we say plainly that none are.
    const emptyState = page.getByText(/Nothing is waiting on you/i);
    const approveButton = page.getByRole("button", { name: /Approve & continue/i });
    await expect(emptyState.or(approveButton).first()).toBeVisible({ timeout: 20_000 });
  });

  test("stacks without horizontal overflow on a phone viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/applications");
    await expect(page.getByRole("heading", { name: /Your job search agent/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });

    // The control center must never force the page to scroll sideways.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, "page should not overflow horizontally on mobile").toBeLessThanOrEqual(1);

    // Overview collapses to a single column rather than the desktop two-column grid.
    const columns = await page.evaluate(() => {
      const grid = document.querySelector('[class*="overviewGrid"]');
      return grid ? getComputedStyle(grid).gridTemplateColumns.split(" ").length : 0;
    });
    expect(columns).toBeLessThanOrEqual(1);
  });

  test("application cards stay readable at desktop width", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/applications?tab=applications");
    await expect(page.getByPlaceholder(/Search company, role, location/i)).toBeVisible({ timeout: 20_000 });

    const card = page.locator('[class*="appCard"]').first();
    await expect(card).toBeVisible({ timeout: 20_000 });

    // Credit-card sized, not a full-width horizontal row.
    const box = await card.boundingBox();
    expect(box, "card should have a layout box").not.toBeNull();
    expect(box!.width).toBeLessThan(600);
  });

  test("diagnostics section renders telemetry", async ({ page }) => {
    await page.goto("/applications?tab=diagnostics");
    await expect(page.getByRole("heading", { name: /Your job search agent/i, level: 1 })).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText(/Latency|Diagnostics|Throughput/i).first()).toBeVisible({ timeout: 20_000 });
  });
});
