import { expect, test } from "@playwright/test";

test("healing remains visible without an active job across Autopilot tabs @local", async ({ page }) => {
  await page.route("**/api/backend/application-assistant/autopilot/events", route => route.abort());
  await page.route("**/api/backend/application-assistant/autopilot/status", route => route.fulfill({ json: {
    status: "COMPLETED", running: false, run: null, activeJob: null, workers: [], queueSize: 0,
    selfHealing: { status: "analyzing", currentRound: 1, maxRounds: 3, patchesApplied: 0, lastPatchSummary: "Inspecting form navigation" },
    recentLogs: [{ id: "healing-test", timestamp: new Date().toISOString(), level: "info", message: "Analyzing failed form navigation" }],
  } }));
  await page.goto("/applications");
  await page.getByRole("button", { name: "Expand activity", exact: true }).click();
  await expect(page.getByText("Self-healing in progress", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("Ready when you are.", { exact: true })).toHaveCount(0);
  for (const name of ["Applications", "Review", "Diagnostics", "Overview"]) {
    await page.locator("nav").getByRole("button", { name: new RegExp(`^${name}`) }).click();
    await expect(page.getByText("Live Autopilot Activity", { exact: true })).toBeVisible();
    await expect(page.getByText("Self-healing in progress", { exact: true }).last()).toBeVisible();
    await expect(page.getByRole("region", { name: "Latest three submissions" })).toBeVisible();
  }
  await page.screenshot({ path: "test-results/healing-activity.png" });
});
