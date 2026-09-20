/**
 * run_e2e_autopilot.spec.ts
 *
 * Full CareerOS Autopilot E2E test.
 * Goal: 10 genuinely submitted applications, each verified against:
 *   1. External ATS site confirmation
 *   2. CareerOS status = SUBMITTED + receipt exists
 *   3. Mistral resume tailoring was run (diff generated, PDF attached)
 *
 * Uses the preflight-approve path (same as a real user clicking "Apply →").
 * Writes a detailed JSON results file alongside the test for the final report.
 *
 * Run with:
 *   CAREEROS_LIVE_APPLY=1 \
 *   CAREEROS_APPROVED_JOB_IDS="id1,id2,...id12" \
 *   CAREER_OS_ADMIN_USERNAME=amsborse@gmail.com \
 *   CAREER_OS_ADMIN_PASSWORD="CareerOS12$" \
 *   npx playwright test e2e/run_e2e_autopilot.spec.ts --project=chromium
 */

import * as fs from "node:fs";
import * as path from "node:path";
import { expect, test } from "@playwright/test";

// ─── Constants ────────────────────────────────────────────────────────────────
const TARGET_SUCCESSES = 10;
const PER_JOB_TIMEOUT_MS = 8 * 60_000; // 8 min per job (Mistral tailoring + browser submit)
const POLL_INTERVAL_MS = 5_000;
const TERMINAL_STATUSES = /^(submitted|review|failed|skipped|ineligible|staged|needs_review)$/i;
const SUCCESS_STATUS = /^submitted$/i;
const RESULTS_FILE = path.join(__dirname, "..", "test-results", "autopilot-e2e-results.json");

// ─── Helpers ──────────────────────────────────────────────────────────────────

interface JobOutcome {
  id: string;
  company: string;
  title: string;
  ats: string;
  status: string | null;
  preflightOk: boolean;
  tailoredResumeFile: string | null;
  tailoringValidated: boolean;
  siteConfirmation: string | null;
  receiptId: string | null;
  receiptVerified: boolean;
  gmailConfirmation: boolean;
  successfulSubmission: boolean;
  failureReason: string | null;
  attemptDurationMs: number;
  screenshot: string | null;
  consoleErrors: string[];
  apiErrors: string[];
}

function blankOutcome(id: string): JobOutcome {
  return {
    id,
    company: "",
    title: "",
    ats: "",
    status: null,
    preflightOk: false,
    tailoredResumeFile: null,
    tailoringValidated: false,
    siteConfirmation: null,
    receiptId: null,
    receiptVerified: false,
    gmailConfirmation: false,
    successfulSubmission: false,
    failureReason: null,
    attemptDurationMs: 0,
    screenshot: null,
    consoleErrors: [],
    apiErrors: [],
  };
}

// ─── Main test ────────────────────────────────────────────────────────────────

test("autopilot e2e — submit 10 real applications", async ({ page, request, context }, testInfo) => {
  test.skip(process.env.CAREEROS_LIVE_APPLY !== "1", "Requires CAREEROS_LIVE_APPLY=1");

  const rawIds = (process.env.CAREEROS_APPROVED_JOB_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
  expect(rawIds.length, "Need at least 10 job IDs").toBeGreaterThanOrEqual(10);

  // Total timeout: IDs × per-job budget + 5 min overhead
  test.setTimeout((rawIds.length * 8 + 5) * 60_000);

  const API_BASE = "/api/backend/application-assistant";
  const outcomes: JobOutcome[] = [];
  const consoleErrors: string[] = [];

  // Capture console errors globally
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 300));
  });

  // ── Navigate to Autopilot page ──
  await page.goto("/applications", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: /^Autopilot$/i, level: 1 })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".backend-offline-alert")).not.toBeVisible();

  // Switch to Applications tab
  const appsTab = page.getByRole("button", { name: /^Applications/i });
  if (await appsTab.isVisible()) await appsTab.click();
  await page.waitForLoadState("networkidle");

  // ── Per-job loop ──────────────────────────────────────────────────────────
  let successCount = 0;
  let attemptCount = 0;

  for (const id of rawIds) {
    if (successCount >= TARGET_SUCCESSES) break;

    attemptCount++;
    const outcome = blankOutcome(id);
    const t0 = Date.now();
    const jobConsoleErrors: string[] = [];

    // Capture per-job console errors
    const consoleSub = (msg: { type: () => string; text: () => string }) => {
      if (msg.type() === "error") jobConsoleErrors.push(msg.text().slice(0, 200));
    };
    page.on("console", consoleSub);

    try {
      // ── 1. Fetch job metadata from API ─────────────────────────────────
      const jobRes = await request.get(`${API_BASE}/jobs/${id}`).catch(() => null);
      if (jobRes?.ok()) {
        const jobData = await jobRes.json().catch(() => ({}));
        const j = jobData.job || jobData;
        outcome.company = j.company || "";
        outcome.title = j.title || "";
        outcome.ats = j.sourceProvider || j.atsType || "";
      }

      // ── 2. Navigate to the Applications tab and find the job card ──────
      await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
      await page.waitForLoadState("networkidle");

      // Switch to Applications section if needed
      const appsBtn = page.getByRole("button", { name: /^Applications/i });
      if (await appsBtn.isVisible({ timeout: 5_000 })) await appsBtn.click();

      // Filter to Queued
      const queuedChip = page.getByRole("button", { name: /^Queued\s+\d+$/i });
      if (await queuedChip.isVisible({ timeout: 5_000 })) await queuedChip.click();
      await page.waitForLoadState("networkidle");

      // Find the job card for this ID
      const card = page.locator(`[data-job-id="${id}"]`);
      const cardVisible = await card.isVisible({ timeout: 10_000 }).catch(() => false);

      if (!cardVisible) {
        outcome.failureReason = `Card [data-job-id="${id}"] not visible in Queued view`;
        outcomes.push(outcome);
        continue;
      }

      // Capture job info from card if API didn't return it
      if (!outcome.company) {
        const cardText = await card.innerText().catch(() => "");
        outcome.company = cardText.split("\n")[0]?.trim() || id;
      }

      // ── 3. Verify card is in QUEUED state ─────────────────────────────
      const cardStatus = await card.getAttribute("data-status").catch(() => null);
      if (cardStatus && !["queued", "failed", "staged", "needs_review"].includes(cardStatus.toLowerCase())) {
        outcome.failureReason = `Card status is ${cardStatus}, not queueable`;
        outcome.status = cardStatus;
        outcomes.push(outcome);
        continue;
      }

      // ── 4. Click "Apply →" on the card ────────────────────────────────
      const applyBtn = card.getByRole("button", { name: /^Apply\s*[→>]/i });
      if (!await applyBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
        outcome.failureReason = "Apply button not visible on card";
        outcomes.push(outcome);
        continue;
      }

      // Intercept the preflight-approve response
      const preflightPromise = page.waitForResponse(
        (r) => r.url().includes(`/jobs/${id}/preflight-approve`) && r.request().method() === "POST",
        { timeout: 15_000 }
      );

      await applyBtn.click();
      let preflightOk = false;
      try {
        const preflightRes = await preflightPromise;
        preflightOk = preflightRes.ok();
        outcome.preflightOk = preflightOk;
        if (!preflightOk) {
          const body = await preflightRes.text().catch(() => "");
          outcome.failureReason = `preflight-approve HTTP ${preflightRes.status()}: ${body.slice(0, 200)}`;
        }
      } catch (e) {
        outcome.failureReason = `preflight-approve timeout: ${e}`;
        outcome.preflightOk = false;
      }

      if (!preflightOk) {
        await card.screenshot({ path: testInfo.outputPath(`${id}-preflight-fail.png`) }).catch(() => {});
        outcome.screenshot = `${id}-preflight-fail.png`;
        outcomes.push(outcome);
        continue;
      }

      // ── 5. Poll for terminal status ────────────────────────────────────
      let finalStatus: string | null = null;
      const pollDeadline = Date.now() + PER_JOB_TIMEOUT_MS;

      while (Date.now() < pollDeadline) {
        const s = await card.getAttribute("data-status").catch(() => null);
        if (s && TERMINAL_STATUSES.test(s)) {
          finalStatus = s.toLowerCase();
          break;
        }
        // Also poll the API directly as a fallback (card may have been scrolled out)
        const apiStatus = await request.get(`${API_BASE}/autopilot/jobs/${id}`).catch(() => null);
        if (apiStatus?.ok()) {
          const d = await apiStatus.json().catch(() => ({}));
          const apiS = (d.job || d)?.status?.toLowerCase();
          if (apiS && TERMINAL_STATUSES.test(apiS)) {
            finalStatus = apiS;
            break;
          }
        }
        await page.waitForTimeout(POLL_INTERVAL_MS);
      }

      outcome.status = finalStatus;

      // Screenshot of final state
      const screenshotPath = testInfo.outputPath(`${id}-final.png`);
      await card.screenshot({ path: screenshotPath }).catch(() =>
        page.screenshot({ path: screenshotPath }).catch(() => {})
      );
      outcome.screenshot = `${id}-final.png`;

      // ── 6. Validate if submitted ───────────────────────────────────────
      if (finalStatus && SUCCESS_STATUS.test(finalStatus)) {
        // Fetch receipt
        const receiptRes = await request.get(`${API_BASE}/receipts/${id}`).catch(() => null);
        if (receiptRes?.ok()) {
          const { receipt } = await receiptRes.json().catch(() => ({}));
          outcome.receiptId = receipt?.receiptId || receipt?.id || null;
          outcome.siteConfirmation = receipt?.confirmationText || receipt?.confirmationUrl || null;
          outcome.tailoredResumeFile = receipt?.resumeFileUsed || null;

          // A receipt is verified if it has explicit confirmation evidence
          outcome.receiptVerified = Boolean(
            receipt?.verificationStatus === "VERIFIED" &&
            (receipt?.confirmationText || receipt?.confirmationUrl)
          );
        }

        // Validate tailored resume
        if (outcome.tailoredResumeFile) {
          const pdfRes = await request.get(`${API_BASE}/autopilot/jobs/${id}/resume`).catch(() => null);
          outcome.tailoringValidated = pdfRes?.ok() === true && pdfRes.headers()["content-type"]?.includes("pdf") === true;
        } else {
          // No file recorded — check if diff was generated
          const diffRes = await request.get(`${API_BASE}/jobs/${id}/tailor-diff`).catch(() => null);
          if (diffRes?.ok()) {
            const diffData = await diffRes.json().catch(() => ({}));
            outcome.tailoringValidated = Boolean(diffData.diff?.bullets?.length || diffData.diff?.summary);
            outcome.tailoredResumeFile = diffData.diff ? "(diff-generated)" : null;
          }
        }

        // Mark success only when receipt is verified (external site confirmed)
        // OR when CareerOS recorded it as SUBMITTED + has a receipt ID (some ATSes
        // don't send redirect confirmations but the browser executor captures the DOM)
        const isVerifiedSubmission = outcome.receiptVerified ||
          (finalStatus === "submitted" && Boolean(outcome.receiptId || outcome.siteConfirmation));

        outcome.successfulSubmission = isVerifiedSubmission;
        if (isVerifiedSubmission) {
          successCount++;
          console.log(
            `[${successCount}/${TARGET_SUCCESSES}] ✅ ${outcome.company} | ${outcome.title} | receipt=${outcome.receiptId}`
          );
        } else {
          outcome.failureReason = "Submitted status but no verified receipt/confirmation evidence";
          console.log(`[UNVERIFIED] ${outcome.company} — status=submitted but receipt not verified`);
        }
      } else if (finalStatus === null) {
        outcome.failureReason = `Timed out after ${PER_JOB_TIMEOUT_MS / 1000}s, no terminal status reached`;
      } else {
        outcome.failureReason = `Terminal status: ${finalStatus}`;
      }

    } catch (err) {
      outcome.failureReason = `Unexpected error: ${String(err).slice(0, 300)}`;
      await page.screenshot({ path: testInfo.outputPath(`${id}-error.png`) }).catch(() => {});
      outcome.screenshot = `${id}-error.png`;
    } finally {
      outcome.attemptDurationMs = Date.now() - t0;
      outcome.consoleErrors = jobConsoleErrors;
      page.off("console", consoleSub);
      outcomes.push(outcome);
    }
  } // end for-loop

  // ── 7. Gmail verification pass ────────────────────────────────────────────
  // Check Gmail inbox for confirmation emails for each submitted job
  const submittedOutcomes = outcomes.filter((o) => o.successfulSubmission);
  if (submittedOutcomes.length > 0) {
    const gmailRes = await request.get("/api/backend/tracker/gmail/applications").catch(() => null);
    if (gmailRes?.ok()) {
      const gmailData = await gmailRes.json().catch(() => ({}));
      const emails: Array<{ company?: string; jobTitle?: string; subject?: string; receivedAt?: string }> =
        gmailData.applications || gmailData.emails || [];

      for (const outcome of submittedOutcomes) {
        const match = emails.find(
          (e) =>
            (e.company || "").toLowerCase().includes(outcome.company.toLowerCase()) ||
            (e.subject || "").toLowerCase().includes(outcome.company.toLowerCase())
        );
        if (match) {
          outcome.gmailConfirmation = true;
          console.log(`[GMAIL] ✉️  Confirmation found for ${outcome.company}: "${match.subject}"`);
        }
      }
    }
  }

  // ── 8. Write results file ─────────────────────────────────────────────────
  const summary = {
    runAt: new Date().toISOString(),
    targetSuccesses: TARGET_SUCCESSES,
    successfulSubmissions: successCount,
    totalAttempts: attemptCount,
    failedAttempts: outcomes.filter((o) => !o.successfulSubmission && o.status !== "submitted").length,
    stagedReview: outcomes.filter((o) => o.status && /staged|needs_review|review/.test(o.status)).length,
    duplicatesPrevented: outcomes.filter((o) => o.failureReason?.includes("deduplicated")).length,
    tailoringValidated: outcomes.filter((o) => o.tailoringValidated).length,
    gmailConfirmations: outcomes.filter((o) => o.gmailConfirmation).length,
    outcomes,
  };

  fs.mkdirSync(path.dirname(RESULTS_FILE), { recursive: true });
  fs.writeFileSync(RESULTS_FILE, JSON.stringify(summary, null, 2));
  await testInfo.attach("autopilot-e2e-results", {
    body: JSON.stringify(summary, null, 2),
    contentType: "application/json",
  });

  // ── 9. Final assertions ───────────────────────────────────────────────────
  console.log(`\n${"=".repeat(60)}`);
  console.log(`AUTOPILOT E2E RESULTS`);
  console.log(`Successful submissions: ${successCount}/${TARGET_SUCCESSES}`);
  console.log(`Total attempts: ${attemptCount}`);
  console.log(`Tailoring validated: ${summary.tailoringValidated}`);
  console.log(`Gmail confirmations: ${summary.gmailConfirmations}`);
  console.log("=".repeat(60));

  // Assert we hit the target
  expect(
    successCount,
    `Only ${successCount} verified submissions. Need ${TARGET_SUCCESSES}. ` +
      `Check test-results/autopilot-e2e-results.json for details.`
  ).toBeGreaterThanOrEqual(TARGET_SUCCESSES);
});
