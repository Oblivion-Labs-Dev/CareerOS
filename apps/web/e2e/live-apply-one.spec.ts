import { test } from "@playwright/test";
import fs from "node:fs";

/**
 * Drives ONE application end-to-end through the real Autopilot UI.
 *
 * Deliberately different from run-single-ui-applications.spec.ts: that spec
 * aborts the whole exercise on the first non-submitted job, which is the wrong
 * shape for an operator loop that must diagnose a failure and retry. This one
 * never throws on an application outcome — it records what actually happened to
 * CAREEROS_OUT_FILE so the caller can classify it (bug to fix, unanswerable
 * question to skip, transient failure to retry) and then run the next job.
 */
test("apply to one job through the Autopilot UI", async ({ page, request }, testInfo) => {
  test.skip(process.env.CAREEROS_LIVE_APPLY !== "1", "Requires explicit live application opt-in");
  const id = (process.env.CAREEROS_JOB_ID || "").trim();
  const search = (process.env.CAREEROS_JOB_SEARCH || "").trim();
  const outFile = process.env.CAREEROS_OUT_FILE || testInfo.outputPath("outcome.json");
  test.setTimeout(14 * 60_000);

  const outcome: Record<string, unknown> = { id, search, verified: false, stage: "start" };
  const consoleErrors: string[] = [];
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 300)); });
  page.on("pageerror", e => consoleErrors.push(`pageerror: ${String(e).slice(0, 300)}`));

  const write = () => {
    outcome.consoleErrors = consoleErrors.slice(0, 25);
    fs.writeFileSync(outFile, JSON.stringify(outcome, null, 2));
  };

  try {
    await page.goto("/applications", { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Applications", exact: true }).click();
    outcome.stage = "applications-tab";

    // Search narrows server-side, which is the only reliable way to surface one
    // card out of a 360-job infinite-scroll list.
    if (search) {
      await page.getByPlaceholder("Search company, role, location…").fill(search);
      await page.waitForTimeout(1500);
    }

    const card = page.locator(`[data-job-id="${id}"]`);
    await card.waitFor({ state: "visible", timeout: 30_000 });
    outcome.stage = "card-visible";
    outcome.statusBefore = await card.getAttribute("data-status");
    outcome.textBefore = (await card.innerText()).replace(/\s+/g, " ").slice(0, 400);

    const accepted = page
      .waitForResponse(r => r.url().includes(`/jobs/${id}/preflight-approve`) && r.request().method() === "POST", { timeout: 60_000 })
      .catch(() => null);
    await card.getByRole("button", { name: "Apply →", exact: true }).click();
    const res = await accepted;
    outcome.stage = "apply-clicked";
    outcome.preflightStatus = res ? res.status() : "no-response";
    if (res) outcome.preflightBody = (await res.text().catch(() => "")).slice(0, 400);

    // Poll this exact card's status. The list refreshes on its own; re-reading
    // the attribute each tick avoids trusting a stale render.
    const terminal = /^(submitted|review|failed|skipped|ineligible)$/;
    const deadline = Date.now() + 11 * 60_000;
    let status = "";
    while (Date.now() < deadline) {
      status = (await card.getAttribute("data-status").catch(() => null)) || "";
      if (terminal.test(status)) break;
      await page.waitForTimeout(5_000);
    }
    outcome.stage = "terminal";
    outcome.status = status;
    outcome.textAfter = (await card.innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 800);
    await card.screenshot({ path: testInfo.outputPath(`${id}.png`) }).catch(() => {});
    outcome.screenshot = testInfo.outputPath(`${id}.png`);

    if (status === "submitted") {
      const r = await request.get(`/api/backend/application-assistant/receipts/${id}`);
      outcome.receiptHttp = r.status();
      if (r.ok()) {
        const { receipt } = await r.json();
        outcome.receiptId = receipt?.receiptId;
        outcome.verificationStatus = receipt?.verificationStatus;
        outcome.confirmationUrl = receipt?.confirmationUrl;
        outcome.confirmationText = String(receipt?.confirmationText || "").slice(0, 300);
        outcome.verified = receipt?.verificationStatus === "VERIFIED" && Boolean(receipt?.confirmationText || receipt?.confirmationUrl);
      }
    }
  } catch (err) {
    outcome.error = String(err).slice(0, 600);
  } finally {
    write();
    await testInfo.attach("outcome", { body: JSON.stringify(outcome, null, 2), contentType: "application/json" });
    console.log("OUTCOME " + JSON.stringify(outcome));
  }
});
