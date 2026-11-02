import { expect, test } from "@playwright/test";

test("inbox request is valid and message previews work @local", async ({ page }) => {
  test.setTimeout(90000);
  const responsePromise = page.waitForResponse(response => response.url().includes("/email/recruiter-threads/classified"), { timeout: 70000 });
  await page.goto("/applications?tab=inbox");
  const response = await responsePromise;
  expect(new URL(response.url()).searchParams.get("limit")).toBe("100");
  expect(response.status()).not.toBe(422);
  expect(response.ok(), await response.text()).toBe(true);
  const data = await response.json();
  if (data.threads.length) {
    const messages = page.getByRole("region", { name: "Recruiter messages" });
    await messages.locator('button[aria-pressed]').first().click();
    await expect(page.getByRole("complementary", { name: "Message preview" }).getByRole("heading")).toHaveText(data.threads[0].subject || "No subject");
  }
  await page.screenshot({ path: "test-results/inbox-workspace.png" });
});

test("pipeline renders backend stages and contains mobile overflow", async ({ page }) => {
  await page.goto("/applications?tab=pipeline");
  await expect(page.getByText("TRACKED OPPORTUNITIES")).toBeVisible({ timeout: 20000 });
  const response = await page.request.get("/api/backend/tracker/pipeline");
  expect(response.ok()).toBe(true);
  const data = await response.json();
  for (const column of data.columns) await expect(page.getByRole("region", { name: `${column.label} applications`, exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/pipeline-workspace.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
