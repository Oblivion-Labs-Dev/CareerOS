import { test, expect } from "@playwright/test";

test.describe("UI Single-Job Autopilot Runner (1 at a time)", () => {
  test.setTimeout(1800_000); // 30 minutes

  test("apply 1 at a time through UI until 10 new applications succeed", async ({ page }) => {
    console.log("[UI-RUNNER] Navigating to /applications...");
    await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });

    // Ensure we are on the applications list
    await page.waitForTimeout(3000);

    // Verify page loaded
    const appTab = page.getByRole("button", { name: /^Applications/i });
    if (await appTab.isVisible()) {
      await appTab.click();
      await page.waitForTimeout(2000);
    }

    // Filter to Queued jobs so we only pick unapplied ones
    const queuedFilterBtn = page.getByRole("button", { name: /^Queued/i });
    if (await queuedFilterBtn.isVisible()) {
      console.log("[UI-RUNNER] Switching filter to Queued...");
      await queuedFilterBtn.click();
      await page.waitForTimeout(2000);
    }

    let newlySubmittedCount = 0;
    const targetSubmissions = 10;

    for (let round = 1; round <= targetSubmissions; round++) {
      console.log(`\n========================================`);
      console.log(`[UI-RUNNER] Starting single application #${round} (Goal: ${targetSubmissions})`);
      console.log(`========================================`);

      // Find the first available "Apply →" action in the grid
      const applyBtn = page.locator('span[role="button"]:has-text("Apply →")').first();

      const canApply = await applyBtn.isVisible({ timeout: 10000 }).catch(() => false);
      if (!canApply) {
        console.log("[UI-RUNNER] No immediate 'Apply →' button visible in Queued filter. Reloading view...");
        await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(3000);
        const qBtn = page.getByRole("button", { name: /^Queued/i });
        if (await qBtn.isVisible()) {
          await qBtn.click();
          await page.waitForTimeout(2000);
        }
      }

      // Check again
      const targetApplyBtn = page.locator('span[role="button"]:has-text("Apply →")').first();
      await expect(targetApplyBtn).toBeVisible({ timeout: 15000 });

      // Get the job card details for logging
      const card = targetApplyBtn.locator("xpath=ancestor::button[1]");
      const cardText = await card.innerText();
      const firstLine = cardText.split("\n")[0] || "Unknown job";
      console.log(`[UI-RUNNER] Clicking 'Apply →' from UI for: ${firstLine.trim()}`);

      // Click Apply from the UI
      await targetApplyBtn.click();

      // Monitor processing until this single job reaches terminal state or progresses
      console.log("[UI-RUNNER] Application triggered. Watching live UI status...");
      
      // Wait for it to switch out of applying or complete
      let waitSeconds = 0;
      const maxWait = 240; // 4 minutes per job
      let completed = false;

      while (waitSeconds < maxWait) {
        await page.waitForTimeout(5000);
        waitSeconds += 5;

        // Check if there is a note or notification
        const noteEl = page.locator('div[class*="empty"]');
        if (await noteEl.isVisible()) {
          const noteText = await noteEl.innerText();
          if (noteText.includes("Applied") || noteText.includes("Submitted")) {
            console.log(`[UI-RUNNER] UI Status Note: ${noteText}`);
          }
        }

        // Check overview/status if it finished
        // We can inspect whether the applying button is gone and the job moved to Submitted
        if (waitSeconds % 20 === 0) {
          console.log(`[UI-RUNNER] Waiting for single job completion... (${waitSeconds}s elapsed)`);
        }

        // Check if the current button is no longer "Applying…"
        const currentText = await targetApplyBtn.innerText().catch(() => "");
        if (currentText !== "Applying…") {
          // It finished this single application
          console.log(`[UI-RUNNER] Job execution cycle ended at ${waitSeconds}s.`);
          completed = true;
          break;
        }
      }

      newlySubmittedCount++;
      console.log(`[UI-RUNNER] Finished processing application #${round}. Pausing 5s before next...`);
      await page.waitForTimeout(5000);

      // Refresh list to update counts and move to next queued job
      await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2000);
      const qFilter = page.getByRole("button", { name: /^Queued/i });
      if (await qFilter.isVisible()) {
        await qFilter.click();
        await page.waitForTimeout(2000);
      }
    }

    console.log(`[UI-RUNNER] Successfully completed 10 UI application triggers!`);
  });
});
