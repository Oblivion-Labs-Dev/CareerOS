import { expect, test } from "@playwright/test";

test("journey opens the selected application's backend evidence", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=submitted");
  const card = page.locator('article[data-job-id][data-status="submitted"]').first();
  await expect(card).toBeVisible({ timeout: 20000 });
  const id = await card.getAttribute("data-job-id");
  const response = await page.request.get(`/api/backend/application-assistant/jobs/${id}/journey`);
  expect(response.ok()).toBe(true);
  const data = await response.json();
  expect(data.jobId).toBe(id);
  await card.locator("button").first().click();
  const journey = page.getByRole("region", { name: "Connected application journey" });
  await expect(journey.getByRole("heading", { name: data.assessment.label, exact: true })).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Documents", exact: true }).click();
  if (data.receipt) await expect(journey.locator("dd").filter({ hasText: data.receipt.receiptId })).toBeVisible();
  await page.screenshot({ path: "test-results/application-journey.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.getByRole("dialog").evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
});
