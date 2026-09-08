import { test, expect } from "@playwright/test";

test.describe("Autopilot 10 applications runner", () => {
  test.setTimeout(1800_000); // 30 minutes for 10 applications

  test("navigate to autopilot page and process 10 applications", async ({ page }) => {
    console.log("Navigating to /applications...");
    await page.goto("/applications", { waitUntil: "networkidle" });

    const heading = page.getByRole("heading", { name: /Your job search agent/i, level: 1 });
    await expect(heading).toBeVisible({ timeout: 20_000 });
    console.log("On Autopilot page successfully.");

    const statusPill = page.locator('div[class*="statusPill"]');
    await expect(statusPill).toBeVisible({ timeout: 10_000 });
    const currentStatusText = await statusPill.innerText();
    console.log("Current status:", currentStatusText.replace(/\s+/g, " ").trim());

    const startButton = page.getByRole("button", { name: /Start run/i });
    const isRunning = currentStatusText.toLowerCase().includes("running") || currentStatusText.toLowerCase().includes("recovering");

    if (!isRunning && (await startButton.isVisible())) {
      console.log("Clicking 'Start run' button to launch 10 applications batch...");
      await startButton.click();
      console.log("Clicked 'Start run'. Waiting 3 seconds...");
      await page.waitForTimeout(3000);
    } else {
      console.log("Autopilot is already actively processing jobs.");
    }

    let previousLiveRole = "";
    const startTime = Date.now();
    const maxDurationMs = 1500_000; // 25 minutes
    let completedChecks = 0;

    while (Date.now() - startTime < maxDurationMs) {
      await page.waitForTimeout(5000);

      const liveRoleEl = page.locator('div[class*="liveJobRole"]');
      const liveCompEl = page.locator('div[class*="liveJobCompany"]');
      const liveOpEl = page.locator('div[class*="liveOperation"]');

      if (await liveCompEl.isVisible()) {
        const comp = (await liveCompEl.innerText()).trim();
        const role = (await liveRoleEl.isVisible()) ? (await liveRoleEl.innerText()).trim() : "";
        const op = (await liveOpEl.isVisible()) ? (await liveOpEl.innerText()).trim().replace(/\s+/g, " ") : "";
        const roleDesc = `${comp} - ${role}`;
        if (roleDesc !== previousLiveRole) {
          previousLiveRole = roleDesc;
          console.log(`[AUTOPILOT LIVE] ${roleDesc} | Step: ${op}`);
        }
      }

      const stateText = (await statusPill.innerText()).replace(/\s+/g, " ").trim();

      if (stateText.toLowerCase().includes("completed") || stateText.toLowerCase().includes("stopped")) {
        completedChecks += 1;
        if (completedChecks >= 3) {
          console.log(`Autopilot completed batch run: ${stateText}`);
          break;
        }
      } else {
        completedChecks = 0;
      }
    }

    console.log("Autopilot batch execution run concluded.");
  });
});
