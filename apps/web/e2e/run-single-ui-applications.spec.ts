import { expect, test } from "@playwright/test";

// This is an explicit live exercise, never part of an ordinary test run.
test("apply to ten distinct approved jobs, one at a time", async ({ page, request }, testInfo) => {
  test.skip(process.env.CAREEROS_LIVE_APPLY !== "1", "Requires explicit live application opt-in");
  const ids = (process.env.CAREEROS_APPROVED_JOB_IDS || "").split(",").map(id => id.trim()).filter(Boolean);
  expect(ids.length, "Provide at least ten explicitly approved job IDs").toBeGreaterThanOrEqual(10);
  expect(new Set(ids).size, "Jobs must be distinct").toBe(ids.length);
  test.setTimeout((ids.length * 7 + 1) * 60_000);
  const outcomes: Record<string, unknown>[] = [];
  const api = "/api/backend/application-assistant";
  await page.goto("/applications", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Applications", exact: true }).click();
  try {
    for (const id of ids) {
      if (outcomes.filter(outcome => outcome.verified === true).length === 10) break;
      const card = page.locator(`[data-job-id="${id}"]`);
      await expect(card).toHaveAttribute("data-status", "queued");
      const before = await card.innerText();
      const accepted = page.waitForResponse(r => r.url().endsWith(`/jobs/${id}/preflight-approve`) && r.request().method() === "POST");
      await card.getByRole("button", { name: "Apply →", exact: true }).click();
      expect((await accepted).ok(), `${id}: application request accepted`).toBeTruthy();
      // Never infer success from a disappearing button. Wait for this exact
      // job's terminal status; a timeout stops the exercise, preventing overlap.
      await expect(card).toHaveAttribute("data-status", /^(submitted|review|failed|skipped|ineligible)$/, { timeout: 6 * 60_000 });
      const status = await card.getAttribute("data-status");
      const outcome: Record<string, unknown> = { id, before, status, details: await card.innerText() };
      await card.screenshot({ path: testInfo.outputPath(`${id}.png`) });
      if (status === "submitted") {
        const response = await request.get(`${api}/receipts/${id}`);
        expect(response.ok(), `${id}: receipt exists`).toBeTruthy();
        const { receipt } = await response.json();
        outcome.receiptId = receipt?.receiptId;
        outcome.verified = receipt?.verificationStatus === "VERIFIED" && Boolean(receipt?.confirmationText || receipt?.confirmationUrl);
        expect(outcome.verified, `${id}: explicit submission evidence`).toBeTruthy();
      }
      outcomes.push(outcome);
      console.log(JSON.stringify(outcome));
    }
  } finally {
    await testInfo.attach("application-outcomes", { body: JSON.stringify(outcomes, null, 2), contentType: "application/json" });
  }
  expect(outcomes.filter(o => o.verified).length, "All ten must have verified submission receipts to report ten successes").toBe(10);
});
