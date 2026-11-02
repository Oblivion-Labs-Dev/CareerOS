import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Live Autopilot exercise: click Apply on real Autopilot cards until three
 * applications are recorded as SUBMITTED with a verified submission receipt.
 *
 * This is an explicit live exercise and never part of an ordinary test run —
 * it submits real applications to real employers. It is gated behind
 * CAREEROS_LIVE_APPLY=1 and, when supplied, an explicit allowlist of approved
 * job ids.
 *
 * Nothing here counts unless CareerOS itself recorded the exact job as
 * `submitted` AND the receipt carries explicit confirmation evidence. Failed,
 * skipped, ineligible, review-required, duplicated and merely-clicked
 * applications are all recorded as attempts and never as successes.
 */

const TARGET_SUBMISSIONS = Number(process.env.CAREEROS_TARGET_SUBMISSIONS || 3);
const API = "/api/backend/application-assistant";
// The employer's form, the Mistral resume tailoring pass and the browser
// verification read-back all happen inside one Apply; on this hardware that
// runs into several minutes for a slow ATS.
const TERMINAL_TIMEOUT_MS = 8 * 60_000;

type Attempt = {
  id: string;
  company: string;
  title: string;
  location: string;
  matchScore: string;
  status: string | null;
  receiptId?: string;
  resumeFileUsed?: string;
  tailoringMode?: string;
  confirmation?: string;
  /** False when the runner fell back to the static template instead of tailoring. */
  tailored?: boolean;
  verified: boolean;
  note?: string;
};

function approvedIds(): string[] {
  return (process.env.CAREEROS_APPROVED_JOB_IDS || "")
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean);
}

/** Text of a card region, trimmed to something readable in the report. */
async function cardField(card: Locator, selectorText: RegExp): Promise<string> {
  const text = await card.innerText().catch(() => "");
  const line = text.split("\n").find((l) => selectorText.test(l));
  return (line || "").trim();
}

/**
 * Queued cards in the Autopilot Applications view are rendered in the backend's
 * own claim order (priorityRank mirrors job_filter_ranker.queue_priority_score:
 * Washington Senior SWE, then related Washington engineering, then US Senior
 * SWE). Reading them straight from the DOM is therefore the same ordering
 * Autopilot itself applies in — no re-sorting in the test.
 */
async function queuedCardIds(page: Page): Promise<string[]> {
  const ids = await page.locator('[data-job-id][data-status="queued"]').evaluateAll(
    (nodes) => nodes.map((n) => n.getAttribute("data-job-id") || "").filter(Boolean),
  );
  const allowlist = approvedIds();
  return allowlist.length > 0 ? ids.filter((id) => allowlist.includes(id)) : ids;
}

test("apply through the Autopilot UI until three applications are verifiably submitted", async ({ page, request }, testInfo) => {
  test.skip(process.env.CAREEROS_LIVE_APPLY !== "1", "Requires explicit live application opt-in");
  test.setTimeout((TARGET_SUBMISSIONS * 4 + 2) * TERMINAL_TIMEOUT_MS / 60_000 * 60_000);

  const attempts: Attempt[] = [];
  const tried = new Set<string>();
  let submitted = 0;

  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Applications", exact: true }).first().click();
  await page.locator("[data-job-id]").first().waitFor({ timeout: 60_000 });

  try {
    while (submitted < TARGET_SUBMISSIONS) {
      const candidates = (await queuedCardIds(page)).filter((id) => !tried.has(id));
      if (candidates.length === 0) {
        // The background preprocessor keeps preparing jobs while an
        // application runs, so an empty queue right now is not necessarily an
        // empty queue in a minute. Refresh once and re-check before giving up.
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.waitForTimeout(15_000);
        const refreshed = (await queuedCardIds(page)).filter((id) => !tried.has(id));
        if (refreshed.length === 0) {
          throw new Error(
            `Queue exhausted after ${attempts.length} attempt(s) with ${submitted}/${TARGET_SUBMISSIONS} verified submissions`,
          );
        }
        continue;
      }

      const id = candidates[0];
      tried.add(id);
      const card = page.locator(`[data-job-id="${id}"]`);
      await card.scrollIntoViewIfNeeded();

      const attempt: Attempt = {
        id,
        company: (await card.locator("div").first().innerText().catch(() => "")).split("\n")[0] || "",
        title: await card.getByRole("button").first().innerText().catch(() => ""),
        location: await cardField(card, /⌖/),
        matchScore: await cardField(card, /%/),
        status: null,
        verified: false,
      };

      // Apply → the single Apply endpoint the card's button fires.
      //
      // Acceptance is confirmed by whichever lands first: the POST's own
      // response, or this job leaving `queued`. Both are real evidence that
      // CareerOS took the job, and waiting only on the response is fragile —
      // the client aborts a slow request, so the browser can never see a
      // response for a submission the server did in fact start.
      const accepted = page
        .waitForResponse(
          (r) => r.url().includes(`/jobs/${id}/preflight-approve`) && r.request().method() === "POST",
          { timeout: 150_000 },
        )
        .then((r) => (r.ok() ? "response-ok" : `response-${r.status()}`))
        .catch(() => null);
      const claimed = expect(card)
        .not.toHaveAttribute("data-status", "queued", { timeout: 150_000 })
        .then(() => "left-queue")
        .catch(() => null);

      await card.getByRole("button", { name: "Apply →", exact: true }).click();
      const acceptance = await Promise.race([accepted, claimed]);
      expect(acceptance, `${id}: Apply accepted by CareerOS (response or status change)`).toBeTruthy();
      expect(acceptance, `${id}: Apply was not rejected`).not.toMatch(/^response-[45]/);

      // Never infer success from a button that changed or a request that was
      // accepted. Wait for THIS job's own terminal status.
      await expect(card).toHaveAttribute(
        "data-status",
        /^(submitted|review|failed|skipped|ineligible)$/,
        { timeout: TERMINAL_TIMEOUT_MS },
      );
      attempt.status = await card.getAttribute("data-status");
      await card.screenshot({ path: testInfo.outputPath(`${id}-${attempt.status}.png`) }).catch(() => {});

      if (attempt.status === "submitted") {
        const response = await request.get(`${API}/receipts/${id}`);
        if (!response.ok()) {
          attempt.note = `submitted status but receipt fetch failed (HTTP ${response.status()})`;
        } else {
          const { receipt } = await response.json();
          attempt.receiptId = receipt?.receiptId;
          attempt.resumeFileUsed = receipt?.resumeFileUsed || "";
          attempt.tailoringMode = receipt?.tailoringMode || "";
          attempt.confirmation = String(receipt?.confirmationText || receipt?.confirmationUrl || "").slice(0, 200);
          // A tailored resume actually reaching the employer is part of the
          // pipeline under test, so a submission with no attached resume file
          // is recorded as an attempt, not a success.
          const hasEvidence = Boolean(receipt?.confirmationText || receipt?.confirmationUrl);
          const hasResume = Boolean(receipt?.resumeFileUsed);
          // `resumeFileUsed` alone is not proof of tailoring: when the local
          // model is unavailable the runner still renders a PDF, from the
          // static template, and flags it. A template resume is not the
          // tailored resume this pipeline is supposed to send.
          const jobsRes = await request.get(`${API}/autopilot/jobs?status=SUBMITTED&limit=200`);
          const row = jobsRes.ok()
            ? ((await jobsRes.json()).jobs || []).find((j: { id: string }) => j.id === id)
            : null;
          const tailored = row ? row.resumeTailoringFailed !== true : false;
          attempt.tailored = tailored;
          attempt.verified =
            receipt?.verificationStatus === "VERIFIED" && hasEvidence && hasResume && tailored;
          if (!attempt.verified) {
            attempt.note =
              `receipt incomplete (verification=${receipt?.verificationStatus}, ` +
              `evidence=${hasEvidence}, resume=${hasResume}, tailored=${tailored})`;
          }
        }
      } else {
        attempt.note = await cardField(card, /./);
      }

      if (attempt.verified) submitted += 1;
      attempts.push(attempt);
      console.log(JSON.stringify(attempt));
    }
  } finally {
    await testInfo.attach("autopilot-live-attempts", {
      body: JSON.stringify({ target: TARGET_SUBMISSIONS, submitted, attempts }, null, 2),
      contentType: "application/json",
    });
  }

  expect(submitted, `SUCCESSFULLY_SUBMITTED must reach ${TARGET_SUBMISSIONS}`).toBe(TARGET_SUBMISSIONS);
});
