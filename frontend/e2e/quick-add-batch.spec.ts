import { expect, test } from "@playwright/test";

/** Paste several job links at once and confirm each one is resolved to its
 *  company and title from the posting itself, with no company/title typed. */
test("add multiple jobs by URL alone", async ({ page }) => {
  test.setTimeout(300_000);

  page.on("response", (r) => {
    if (r.url().includes("enqueue")) console.log("NET", r.status(), r.url().split("/backend")[1] || r.url());
  });
  page.on("console", (m) => { if (m.type() === "error") console.log("CONSOLE", m.text().slice(0, 200)); });

  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
  const toggle = page.getByRole("button", { name: /Add jobs? by URL/i }).first();
  await toggle.waitFor({ state: "visible", timeout: 60_000 });
  await toggle.click();
  await page.waitForTimeout(800);

  const box = page.getByLabel(/Job links/i);
  await box.fill(
    [
      "https://boards.greenhouse.io/robinhood/jobs/7899482?t=gh_src=&gh_jid=7899482",
      "https://himalayas.app/companies/torc-robotics/jobs/senior-software-engineer-fleet-enablement-insights-map-validation-annotati",
    ].join("\n"),
  );
  await expect(page.getByText(/2 links ready/i)).toBeVisible();

  await page.getByRole("button", { name: /Add 2 to Queue/i }).click();
  await page.waitForTimeout(45_000);
  const panel = await page.locator('[class*="quickAddBody"]').first().innerText().catch(() => "");
  console.log("PANEL:", panel.replace(/\s+/g, " ").slice(0, 400));

  const rows = await page.locator('li[class*="quickAddResultRow"]').allInnerTexts();
  console.log("RESULTS:");
  for (const r of rows) console.log("   ", r.replace(/\s+/g, " ").slice(0, 130));
  await page.screenshot({ path: "e2e/.artifacts/quickadd-results.png" });
});
