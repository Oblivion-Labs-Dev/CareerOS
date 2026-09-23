import { expect, test } from "@playwright/test";

test("compact dock and detail sections preserve access to evidence @local", async ({ page }) => {
  await page.goto("/applications?tab=submitted");
  await expect(page.getByRole("region", { name: "Live activity dock" })).toBeVisible();
  await page.getByRole("button", { name: "Expand activity", exact: true }).click();
  await expect(page.getByText("Live Autopilot Activity", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Collapse activity" }).click();
  const card = page.locator('article[data-status="submitted"]').first();
  await expect(card).toBeVisible({ timeout: 20000 });
  await card.click();
  const panel = page.getByRole("dialog");
  await expect(panel.getByRole("region", { name: "Application summary" })).toBeVisible();
  await panel.getByRole("button", { name: "Journey", exact: true }).click();
  await expect(panel.getByRole("heading", { name: "One application. The whole story." })).toBeVisible();
  await expect(panel.getByRole("region", { name: "Application summary" })).not.toBeVisible();
  await panel.getByRole("button", { name: "Documents", exact: true }).click();
  await expect(panel.getByRole("heading", { name: "Application documents" })).toBeVisible();
  await page.screenshot({ path: "test-results/refined-details.png" });
  await page.keyboard.press("Escape");
  await expect(card).toBeFocused();
});

test("pipeline search, list view, and mobile stage navigation", async ({ page }) => {
  await page.route("**/tracker/pipeline", route => route.fulfill({ json: { total: 2, ghostThresholdDays: 21, funnel: [], columns: [
    { key: "applied", label: "Applied", items: [{ id: "one", companyName: "Acme", roleTitle: "Engineer", daysInStage: null, daysSinceActivity: 2, followUpOverdue: true }] },
    { key: "interviewing", label: "Interviewing", items: [{ id: "two", companyName: "Other", roleTitle: "Designer", daysInStage: 1 }] },
  ] } }));
  await page.goto("/applications?tab=pipeline");
  await expect(page.getByText("Follow-up overdue")).toBeVisible();
  await expect(page.getByText("2 days since activity")).toBeVisible();
  await page.getByPlaceholder("Search company or role…").fill("Acme");
  await expect(page.getByRole("heading", { name: "Designer", exact: true })).toHaveCount(0);
  const lightMode = page.getByRole("button", { name: "Switch to Light Mode", exact: true });
  if (await lightMode.isVisible()) await lightMode.click();
  await page.getByRole("button", { name: "List", exact: true }).click();
  await expect(page.locator('[data-view="list"]')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByPlaceholder("Search company or role…").clear();
  await page.getByRole("navigation", { name: "Pipeline stages" }).getByRole("button", { name: /Interviewing/ }).click();
  await expect(page.getByRole("region", { name: "Interviewing applications" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Applied applications" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: "test-results/refined-pipeline-mobile.png" });
  await page.goto("/dashboard");
  await page.goto("/applications?tab=pipeline");
  await expect(page.locator('[data-view="list"]')).toBeVisible();
  await expect(page.getByRole("region",{name:"Interviewing applications"})).toBeVisible();
});

test("inbox arrow keys update selected message preview", async ({ page }) => {
  await page.route("**/email/recruiter-threads/classified?*", route => route.fulfill({ json: { success: true, count: 2, categoryCounts: { interview: 2 }, threads: [1,2].map(number => ({ uid: String(number), fromName: "Recruiter", fromAddress: "recruiter@example.com", subject: `Interview ${number}`, snippet: `Preview ${number}`, date: "2026-09-10", category: "interview", categoryLabel: "Interview" })) } }));
  await page.goto("/applications?tab=inbox");
  const messages = page.locator("button[data-message]");
  await messages.first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(messages.nth(1)).toBeFocused();
  await expect(page.getByRole("complementary", { name: "Message preview" }).getByRole("heading", { name: "Interview 2" })).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.screenshot({ path: "test-results/refined-inbox.png" });
});
