import { expect, test } from "@playwright/test";

/** Open one application's side panel and record what happened with it, using
 *  the same state selector a person uses. Logs each step so a failure says
 *  where the path broke rather than just that it did. */
const COMPANY = process.env.MARK_COMPANY || "";
const STATE = process.env.MARK_STATE || "SUBMITTED";

test("record an application's state from the side panel @local", async ({ page }) => {
  test.setTimeout(240_000);
  expect(COMPANY, "set MARK_COMPANY").not.toEqual("");

  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text().slice(0, 200)); });
  const calls: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes("set-state") || r.url().includes("job-states")) {
      calls.push(`${r.status()} ${r.url().split("/application-assistant")[1] || r.url()}`);
    }
  });

  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });

  // Narrow to the bucket first: the search box filters the rows already
  // loaded, so a job further down a 950-row list is not reachable by typing
  // its name alone.
  const bucket = process.env.MARK_FILTER || "Manual";
  const chip = page.getByRole("button", { name: bucket, exact: false }).first();
  await chip.waitFor({ state: "visible", timeout: 60_000 });
  await chip.click();
  await page.waitForTimeout(2500);

  const search = page.getByPlaceholder(/Search company/i);
  await search.waitFor({ state: "visible", timeout: 60_000 });
  await search.fill(COMPANY);
  await page.waitForTimeout(2500);

  // The card exposes a real accessible name ("Open details for <role> at
  // <company>"), which survives the hashed CSS-module class names.
  const card = page.getByRole("button", { name: new RegExp(`at ${COMPANY}$`, "i") }).first();
  await card.waitFor({ state: "visible", timeout: 30_000 });
  await card.scrollIntoViewIfNeeded();
  await card.click();
  await page.waitForTimeout(2500);

  const picker = page.getByLabel(/Set application state/i);
  const visible = await picker.isVisible().catch(() => false);
  console.log("state picker visible:", visible);
  if (!visible) {
    console.log("PANEL TEXT:", (await page.locator('[class*="detail"]').first().innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 400));
    await page.screenshot({ path: "e2e/.artifacts/no-state-picker.png" });
  }
  expect(visible, "state selector should be offered for this bucket").toBeTruthy();

  const options = await picker.locator("option").allTextContents();
  console.log("options:", options.join(" | "));

  await picker.selectOption(STATE);
  await page.waitForTimeout(5000);

  console.log("network:", calls.join(" ; ") || "(no set-state call fired)");
  console.log("console errors:", errors.slice(0, 3).join(" ; ") || "(none)");
  await page.screenshot({ path: "e2e/.artifacts/mark-submitted.png" });
});
