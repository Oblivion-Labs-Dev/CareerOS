import { expect, test } from "@playwright/test";

/**
 * Regression: the match-floor counts on the Night Batch card were derived from
 * the 100 most recently updated jobs of every status, with a missing score
 * counted as 0. Over a queue of thousands with 142 jobs at 60%+, the card said
 * "Only 0 queued jobs clear 60%". Counts now come from the stats aggregate,
 * which counts the whole QUEUED set server-side.
 */
test("floor counts come from the whole queue, not the recent-jobs sample", async ({ page }) => {
  // The recent-jobs sample: 100 rows, none QUEUED (a busy run), several unscored.
  const sample = Array.from({ length: 100 }, (_, i) => ({
    id: `job-${i}`,
    company: `Co ${i}`,
    title: "Engineer",
    status: i % 2 ? "SUBMITTED" : "FAILED",
    matchScore: i % 3 ? null : 72,
    updatedAt: new Date().toISOString(),
  }));
  await page.route("**/api/backend/application-assistant/autopilot/jobs?**", (route) =>
    route.fulfill({ json: { success: true, jobs: sample, total: 100 } }),
  );
  await page.route("**/api/backend/application-assistant/autopilot/stats**", (route) =>
    route.fulfill({
      json: {
        success: true,
        statusCounts: { QUEUED: 2943, SUBMITTED: 765 },
        uiCounts: {},
        companyCountsByStatus: {},
        submittedToday: 3,
        submitted24h: 5,
        queueScoreFloors: { "40": 900, "50": 346, "60": 142, "70": 40, "80": 9, "90": 0 },
        queueScored: 2943,
        queueUnscored: 0,
      },
    }),
  );

  await page.goto("/applications", { waitUntil: "load" });
  const select = page.locator("#night-batch-floor");
  await expect(select).toBeVisible({ timeout: 60_000 });
  await expect(select.locator('option[value="60"]')).toHaveText(/60% and above \(142\)/, { timeout: 30_000 });
  await expect(select.locator('option[value="50"]')).toHaveText(/\(346\)/);
  await expect(page.getByText(/queued jobs? clear/)).toHaveCount(0);
  await expect(page.getByText("Queue is empty")).toHaveCount(0);
});
