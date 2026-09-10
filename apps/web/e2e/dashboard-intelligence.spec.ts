import { expect, test } from "@playwright/test";

test("dashboard metrics agree with backend records", async ({ page }) => {
  await page.goto("/dashboard");
  const records = [];
  let offset = 0;
  while (true) {
    const response = await page.request.get(`/api/backend/application-assistant/autopilot/jobs?limit=1000&offset=${offset}`);
    expect(response.ok()).toBeTruthy();
    const result = await response.json();
    records.push(...result.jobs);
    if (!result.hasMore) break;
    offset += result.jobs.length;
  }
  const section = page.getByRole("region", { name: "Search intelligence" });
  await expect(section.getByRole("status")).toContainText(`All ${records.length} application records`);
  const strong = records.filter(job => job.status === "QUEUED" && typeof job.matchScore === "number" && job.matchScore >= 80).length;
  await expect(section.getByRole("link", { name: /Strong matches ready/ }).locator("strong")).toHaveText(String(strong));
  const companies = new Set(records.filter(job => job.status === "SUBMITTED").map(job => job.company?.trim().toLowerCase()).filter(Boolean));
  await expect(section.getByRole("link", { name: /Companies reached/ }).locator("strong")).toHaveText(String(companies.size));
  await expect(page.getByText("Within reach.")).toHaveCount(0);
  await page.screenshot({ path: "test-results/metrics-dashboard.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test("application cards are landscape and details remain accessible", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=submitted");
  const card = page.locator("article[data-job-id]").first();
  await expect(card).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: "test-results/compact-cards.png" });
  await expect(card).toHaveAttribute("data-status", "submitted");
  const size = await card.boundingBox();
  expect(size!.width / size!.height).toBeGreaterThan(1.2);
  await card.locator("button").first().click();
  await expect(page.getByRole("button", { name: "Close", exact: true })).toBeVisible();
});
