import { expect, test } from "@playwright/test";

/**
 * Drives a full multi-source scrape from the Job Discovery page and asserts
 * that the sources which used to contribute nothing now land jobs in the index.
 *
 * Exercised through the page's own search form (which is what triggers a
 * scrape) rather than by posting to the API, so this covers the real path a
 * user takes.
 */
test("full scrape from the Discover page pulls from every working source", async ({ page, request }) => {
  test.setTimeout(25 * 60 * 1000);

  await page.goto("/jobs/discover");
  await expect(page.locator(".job-discover-dashboard")).toBeVisible({ timeout: 30_000 });

  // The fetch button is gated on the two required filter fields.
  await page.fill('input[name="q"]', "Software Engineer");

  // Location is a multi-select combobox: type into its visible input and press
  // Enter to commit a tag. The form's `location` field itself is hidden.
  const locationInput = page.locator('.cos-multiselect-combobox-wrap input[type="text"]').first();
  await locationInput.click();
  await locationInput.fill("Remote");
  await locationInput.press("Enter");
  await expect(page.locator(".cos-location-tag-pill")).toHaveCount(1, { timeout: 10_000 });

  const fetchButton = page.locator("form.job-discover-filters").getByRole("button", { name: /^Fetch / });
  await expect(fetchButton).toBeEnabled({ timeout: 15_000 });
  await fetchButton.click();

  // Wait for the run to finish: the dashboard drops its scraping class.
  await expect(page.locator(".job-discover-dashboard--scraping")).toHaveCount(1, { timeout: 60_000 });
  await expect(page.locator(".job-discover-dashboard--scraping")).toHaveCount(0, { timeout: 22 * 60 * 1000 });

  // Ground truth: what each source actually contributed on that run.
  const reportRes = await request.get("http://127.0.0.1:4000/jobs/discover/sources/report");
  expect(reportRes.ok()).toBeTruthy();
  const report = await reportRes.json();
  console.log("\n=== per-platform jobs kept ===");
  console.log(JSON.stringify(report.byPlatform, null, 2));
  console.log("=== errors ===");
  console.log(JSON.stringify(report.errors, null, 2));

  const platforms = report.byPlatform as Record<string, number>;

  // The ATS boards that already worked must keep working.
  expect(platforms.greenhouse ?? 0).toBeGreaterThan(0);

  // The regression this guards: these four adapters returned NormalizedJob
  // dataclasses that the persistence path silently threw away, so each one
  // reported healthy while contributing zero rows.
  for (const source of ["jobicy", "hackernews", "himalayas", "github_feed"]) {
    expect(platforms[source] ?? 0, `${source} must contribute jobs`).toBeGreaterThan(0);
  }

  expect(report.totalKept).toBeGreaterThan(0);
});
