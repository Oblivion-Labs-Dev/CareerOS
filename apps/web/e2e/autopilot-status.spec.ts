import { expect, test } from "@playwright/test";

test.describe("Autopilot and Backend Online status", () => {
  test("autopilot page connects to backend and shows healthy status", async ({ page }) => {
    const consoleLogs: string[] = [];
    const failedRequests: string[] = [];

    page.on("console", (msg) => {
      console.log(`[BROWSER CONSOLE ${msg.type()}] ${msg.text()}`);
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
    });
    page.on("requestfailed", (req) => {
      console.log(`[REQUEST FAILED] ${req.method()} ${req.url()} (${req.failure()?.errorText})`);
      failedRequests.push(`${req.method()} ${req.url()} (${req.failure()?.errorText})`);
    });
    page.on("response", (res) => {
      if (res.status() >= 400) {
        console.log(`[HTTP ${res.status()}] ${res.request().method()} ${res.url()}`);
        failedRequests.push(`${res.status()} ${res.request().method()} ${res.url()}`);
      }
    });

    await page.goto("/applications");

    // Wait for the page content to load
    await expect(page.getByRole("heading", { name: "Job Applications & Autopilot", level: 1 })).toBeVisible({ timeout: 15_000 });

    // Ensure the Backend Offline Alert banner is NOT visible
    const offlineAlert = page.locator(".backend-offline-alert");
    await expect(offlineAlert).not.toBeVisible();

    // Check system health header in autopilot dashboard
    const systemHealthSection = page.locator(".autopilot-system-health");
    await expect(systemHealthSection).toBeVisible();

    // System Health should say "All systems operational"
    await expect(page.getByText("All systems operational")).toBeVisible({ timeout: 10_000 });

    // The sub-items should show "healthy" rather than "offline"
    const offlinePills = systemHealthSection.locator(".is-offline");
    await expect(offlinePills).toHaveCount(0);
  });

  test("autopilot shows submitted count and handles Start Run", async ({ page }) => {
    page.on("console", (msg) => console.log(`[BROWSER CONSOLE] ${msg.type()}: ${msg.text()}`));
    page.on("pageerror", (err) => console.log(`[BROWSER PAGEERROR] ${err}`));
    page.on("requestfailed", (req) => console.log(`[REQUEST FAILED] ${req.url()} - ${req.failure()?.errorText}`));
    page.on("response", (res) => {
      console.log(`[RESPONSE] ${res.status()} ${res.url()}`);
    });

    await page.goto("/applications");
    await expect(page.getByRole("heading", { name: "Job Applications & Autopilot", level: 1 })).toBeVisible({ timeout: 15_000 });

    // Verify header submitted button badge exists and has count 9
    const header = page.locator("header");
    const submittedButton = header.getByRole("button", { name: /Submitted/i });
    await expect(submittedButton).toBeVisible();
    await expect(submittedButton).toContainText("9");

    // Click Submitted tab and verify submitted list renders
    await submittedButton.click();
    await expect(page.getByText("Submitted Applications Archive")).toBeVisible({ timeout: 10_000 });

    // Go back to Autopilot tab
    const autopilotButton = header.getByRole("button", { name: /Autopilot/i });
    await autopilotButton.click();

    // Verify Start Run button is visible and clickable
    const startRunBtn = page.getByRole("button", { name: /Start Run/i });
    await expect(startRunBtn).toBeVisible();
    await startRunBtn.click();
  });
});
