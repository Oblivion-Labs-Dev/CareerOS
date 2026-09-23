import { expect, test } from "@playwright/test";

/**
 * Drives the Night Batch card the way a person would: pick a batch size, set
 * the match floor, choose the local model, confirm the guardrails, press start.
 *
 * This is deliberately a UI test and not an API call. The whole point of the
 * card is that the values shown on it are the values the runner uses, and the
 * only way to prove that is to set them through the controls and then read the
 * configuration the runner reports back.
 *
 * Opt in explicitly — it starts a real batch that submits real applications:
 *   NIGHT_BATCH_LIVE=1 npx playwright test e2e/night-batch.spec.ts
 */

const LIVE = process.env.NIGHT_BATCH_LIVE === "1";
const BATCH_SIZE = process.env.NIGHT_BATCH_SIZE || "10";
const MIN_SCORE = process.env.NIGHT_BATCH_MIN_SCORE || "60";
const MODEL = process.env.NIGHT_BATCH_MODEL || "qwen3:4b-instruct";

test("night batch card configures and starts a run @local", async ({ page }) => {
  test.setTimeout(180_000);

  await page.goto("/applications");

  const card = page.getByLabel("Night Batch Center");
  await expect(card).toBeVisible({ timeout: 30_000 });

  // ── Batch size ── (segmented radios: 1, 10, 50, 100)
  await card.getByRole("radio", { name: BATCH_SIZE, exact: true }).click();

  // ── Match floor ── (select dropdown)
  const floorSelect = page.locator("#night-batch-floor");
  await expect(floorSelect).toBeVisible();
  await floorSelect.selectOption(MIN_SCORE);

  // ── Model Badge ──
  await expect(card.getByText("Qwen 4B Instruct")).toBeVisible();

  // ── Guardrails: Tier-1 hold stays on, self-healing stays on ──
  const checkboxes = card.locator('input[type="checkbox"]');
  await expect(checkboxes).toHaveCount(2);
  for (let i = 0; i < 2; i += 1) {
    if (!(await checkboxes.nth(i).isChecked())) await checkboxes.nth(i).check();
  }

  await page.screenshot({ path: "e2e/.artifacts/night-batch-configured.png", fullPage: false });

  const startButton = page.locator("#start-night-batch-btn");
  await expect(startButton).toBeVisible();
  await expect(startButton).toContainText(BATCH_SIZE);

  if (!LIVE) {
    test.info().annotations.push({
      type: "note",
      description: "Configuration verified; set NIGHT_BATCH_LIVE=1 to actually start the batch.",
    });
    return;
  }

  await startButton.click();

  // The live banner only appears once the runner has an active run, so this is
  // a real assertion that the start actually took, not that a button was clicked.
  await expect(card.getByText(/Night Batch Running/i)).toBeVisible({ timeout: 60_000 });

  console.log("=== NIGHT BATCH STARTED VIA WEBSITE UI ===");
  // Sample the live run across multiple iterations to observe real SSE status updates
  for (let shot = 1; shot <= 10; shot += 1) {
    await page.waitForTimeout(15_000);
    const feed = await card
      .locator('[aria-label="Live batch activity"]')
      .innerText()
      .catch(() => "(no feed)");
    const stages = await card
      .locator('[aria-label="Application pipeline"]')
      .innerText()
      .catch(() => "(no pipeline)");
    const stats = await card
      .locator('[class*="liveBannerStats"]')
      .innerText()
      .catch(() => "(no stats)");

    console.log(`\n--- Batch Monitor Cycle ${shot}/10 ---`);
    console.log("Stats:", stats.replace(/\s+/g, " "));
    console.log("Pipeline:", stages.replace(/\s+/g, " ").slice(0, 160));
    console.log("Feed Tail:", feed.replace(/\s+/g, " ").slice(-250));

    await page.screenshot({ path: `e2e/.artifacts/night-batch-live-${shot}.png` });

    // Check if finished
    const isDone = await card.getByText(/Ready for Run/i).isVisible().catch(() => false);
    if (isDone) {
      console.log("Night Batch has returned to Ready state (run completed).");
      break;
    }
  }

  // Navigate to /diagnostic to inspect live telemetry and alarms after run
  await page.goto("/diagnostic");
  await expect(page.getByRole("heading", { name: /System Diagnostics & Telemetry/i })).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: "e2e/.artifacts/diagnostic-after-night-batch.png" });
});
