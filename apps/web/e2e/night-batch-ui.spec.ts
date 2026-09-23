import { expect, test } from "@playwright/test";

/**
 * End-to-end test that drives the Night Batch feature completely through the CareerOS website UI:
 * 1. Opens /applications
 * 2. Verifies the Night Batch Center component and its visual theme
 * 3. Selects batch size 10 (or preset)
 * 4. Sets match score floor
 * 5. Verifies Qwen local model badge
 * 6. Ensures Tier-1 dream company protection guardrails & self-healing are checked
 * 7. Clicks "Start Night Batch (10 Jobs)" directly in the browser
 * 8. Monitors the live execution through the UI (SSE streaming activity feed, step progression, processed/submitted/staged counts)
 * 9. Waits until completion or continuous progress, checking status logs and DOM states
 * 10. Navigates to /diagnostic to inspect health, telemetry, and alarms
 */

const BATCH_SIZE = process.env.NIGHT_BATCH_SIZE || "10";
const MIN_SCORE = process.env.NIGHT_BATCH_MIN_SCORE || "60";

test("Night Batch 10-job execution via CareerOS Website UI with Qwen @local", async ({ page }) => {
  // Allow ample time for processing 10 jobs sequentially via Playwright
  test.setTimeout(900_000); // 15 minutes

  console.log("=== NAVIGATING TO CAREEROS APPLICATIONS PAGE ===");
  await page.goto("/applications");

  const card = page.getByLabel("Night Batch Center");
  await expect(card).toBeVisible({ timeout: 30_000 });

  // 1. Verify visual presence of Night Batch card & theme
  await expect(card.getByRole("heading", { name: "Night Batch Mode", level: 2 })).toBeVisible();
  await expect(card.getByText("AUTONOMOUS FORM-FILL")).toBeVisible();
  await expect(card.getByText("Qwen 4B Instruct")).toBeVisible();

  // 2. Select Batch Size (10 Jobs)
  const sizeRadio = card.getByRole("radio", { name: BATCH_SIZE, exact: true });
  await sizeRadio.click();
  await expect(sizeRadio).toHaveAttribute("aria-checked", "true");

  // 3. Set Minimum Match Score floor
  const floorSelect = page.locator("#night-batch-floor");
  await expect(floorSelect).toBeVisible();
  await floorSelect.selectOption(MIN_SCORE);

  // 4. Ensure Guardrails (Tier-1 Dream Company Protection & Post-batch self-healing)
  const checkboxes = card.locator('input[type="checkbox"]');
  const count = await checkboxes.count();
  for (let i = 0; i < count; i += 1) {
    if (!(await checkboxes.nth(i).isChecked())) {
      await checkboxes.nth(i).check();
    }
  }

  // Capture screenshot of configured card
  await page.screenshot({ path: "e2e/.artifacts/night-batch-ui-ready.png" });

  // 5. Click Start Night Batch directly from the Website UI
  const startButton = page.locator("#start-night-batch-btn");
  await expect(startButton).toBeVisible();
  await expect(startButton).toContainText(BATCH_SIZE);

  console.log(`=== CLICKING START NIGHT BATCH (${BATCH_SIZE} JOBS) VIA UI ===`);
  await startButton.click();

  // 6. Verify live execution banner appears in the UI
  await expect(card.getByText(/Night Batch Running/i)).toBeVisible({ timeout: 60_000 });
  console.log("=== NIGHT BATCH SUCCESSFULLY STARTED & IS LIVE IN UI ===");

  // 7. Monitor the batch execution directly through the Website UI
  let completed = false;
  const targetCountNum = parseInt(BATCH_SIZE, 10) || 10;
  const maxCycles = 60; // up to ~15 minutes of monitoring
  for (let cycle = 1; cycle <= maxCycles; cycle += 1) {
    await page.waitForTimeout(15_000);

    const stats = await card.locator('[class*="liveBannerStats"]').innerText().catch(() => "");
    const liveTitle = await card.locator('[class*="liveJobTitle"]').innerText().catch(() => "");
    const liveStep = await card.locator('[class*="liveJobStep"]').innerText().catch(() => "");
    const feed = await card.locator('[aria-label="Live batch activity"]').innerText().catch(() => "");

    console.log(`\n--- Monitor Cycle ${cycle}/${maxCycles} ---`);
    if (liveTitle) console.log(`Current Job: ${liveTitle.replace(/\s+/g, " ")}`);
    if (liveStep) console.log(`Step: ${liveStep.replace(/\s+/g, " ")}`);
    if (stats) console.log(`Stats: ${stats.replace(/\s+/g, " ")}`);
    if (feed) {
      const recentFeedLines = feed.split("\n").filter((l: string) => l.trim()).slice(-3);
      console.log(`Recent Activity:\n  ${recentFeedLines.join("\n  ")}`);
    }

    await page.screenshot({ path: `e2e/.artifacts/night-batch-live-progress.png` });

    // Check if the card returned to ready state (run finished)
    const isReady = await card.getByText(/Ready for Run/i).isVisible().catch(() => false);
    if (isReady && cycle > 2) {
      console.log("=== NIGHT BATCH RETURNED TO READY STATE (COMPLETED) ===");
      completed = true;
      break;
    }

    // Check if the stats show target processed count reached
    const match = stats.match(/Processed:\s*(\d+)\s*\/\s*(\d+)/i);
    if (match) {
      const currentProcessed = parseInt(match[1], 10);
      if (currentProcessed >= targetCountNum) {
        console.log(`=== NIGHT BATCH REACHED TARGET COUNT (${currentProcessed}/${targetCountNum}) ===`);
        completed = true;
        break;
      }
    }
  }

  // 8. Navigate to /diagnostic to inspect status, logs, and telemetry
  console.log("=== NAVIGATING TO DIAGNOSTICS PAGE ===");
  await page.goto("/diagnostic");
  await expect(page.getByRole("heading", { name: /System Diagnostics & Telemetry/i, level: 1 })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: "e2e/.artifacts/diagnostic-after-night-batch.png" });

  console.log("=== NIGHT BATCH UI TEST COMPLETE ===");
});
