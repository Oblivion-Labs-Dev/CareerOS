import { expect, test } from "@playwright/test";

/**
 * A job held by its employer's rate limit says so, and Apply still works.
 *
 * The backend paces applications per company — 5 a day, 10 a week, 20 a month —
 * and a paced job deliberately keeps its QUEUED status, carrying only
 * `companyCapHoldUntil`. That is the right model (it is queued and wanted, not
 * a dead end) but it meant a held job was pixel-identical to any other queued
 * one, so a queue that was pacing correctly looked like a queue that was stuck.
 *
 * Clicking Apply overrides the limit, so the button must stay enabled and must
 * not look like it will be refused.
 *
 * Every API call here is a local fixture: the whole point is to render a held
 * job, and waiting for the real queue to reach a cap is not a test.
 */

const HOUR = 3600_000;

function jobs(baseURL: string) {
  const now = Date.now();
  return [
    {
      id: "held-day",
      company: "Affirm",
      title: "Senior Software Engineer",
      location: "Remote",
      status: "QUEUED",
      matchScore: 91,
      updatedAt: new Date(now).toISOString(),
      applicationUrl: `${baseURL}/fixture`,
      companyCapHoldUntil: new Date(now + 6 * HOUR).toISOString(),
      companyCapTier: "day",
      companyCapReason: "Affirm has had 5 applications in the last day (limit 5 per day).",
    },
    {
      id: "held-month",
      company: "Anthropic",
      title: "Research Engineer",
      location: "Remote",
      status: "QUEUED",
      matchScore: 88,
      updatedAt: new Date(now).toISOString(),
      applicationUrl: `${baseURL}/fixture`,
      companyCapHoldUntil: new Date(now + 9 * 24 * HOUR).toISOString(),
      companyCapTier: "month",
      companyCapReason: "Anthropic has had 20 applications in the last 30 days.",
    },
    {
      // The control. Without one, "the badge renders" could just mean "the
      // badge renders on everything".
      id: "free",
      company: "Globex",
      title: "Staff Engineer",
      location: "Remote",
      status: "QUEUED",
      matchScore: 84,
      updatedAt: new Date(now).toISOString(),
      applicationUrl: `${baseURL}/fixture`,
    },
    {
      // An expired hold must clear itself from the stored expiry, without the
      // row having to be rewritten by the backend first.
      id: "expired",
      company: "Initech",
      title: "Platform Engineer",
      location: "Remote",
      status: "QUEUED",
      matchScore: 80,
      updatedAt: new Date(now).toISOString(),
      applicationUrl: `${baseURL}/fixture`,
      companyCapHoldUntil: new Date(now - 2 * HOUR).toISOString(),
      companyCapTier: "day",
    },
  ];
}

test("a rate-limited job shows its countdown and still offers Apply", async ({ page, baseURL }) => {
  await page.context().addCookies([
    { name: "co_session", value: "isolated-ui-fixture", url: baseURL! },
  ]);
  const rows = jobs(baseURL!);
  const applied: string[] = [];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET") {
      // Apply goes through the single preflight-approve endpoint.
      if (url.pathname.includes("preflight-approve")) applied.push(url.pathname);
      return route.fulfill({ json: { success: true } });
    }
    if (url.pathname.endsWith("/autopilot/jobs")) {
      return route.fulfill({
        json: {
          success: true,
          jobs: rows,
          total: rows.length,
          hasMore: false,
          statusCounts: { QUEUED: rows.length },
          companyCounts: {},
          titleCounts: {},
        },
      });
    }
    if (url.pathname.endsWith("/autopilot/stats")) {
      return route.fulfill({
        json: {
          success: true,
          statusCounts: { QUEUED: rows.length },
          uiCounts: {},
          companyCountsByStatus: {},
          titleCountsByStatus: {},
        },
      });
    }
    if (url.pathname.endsWith("/auth/status")) return route.fulfill({ json: { authRequired: false } });
    return route.fulfill({
      json: {
        success: true,
        state: { status: "IDLE", workers: [] },
        jobs: [],
        items: [],
        events: [],
        settings: {},
        profile: {},
        preferences: {},
      },
    });
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");

  const card = (id: string) => page.locator(`article[data-job-id="${id}"]`);
  await expect(card("held-day")).toBeVisible({ timeout: 60_000 });

  // The countdown is shown, in the units the wait actually warrants.
  await expect(card("held-day")).toContainText(/Paced · 6h/);
  await expect(card("held-month")).toContainText(/Paced · 9d/);

  // And it explains which limit bound, rather than just "paced".
  await expect(card("held-day").getByTitle(/daily limit/)).toBeVisible();
  await expect(card("held-month").getByTitle(/monthly limit/)).toBeVisible();

  // A job with room, and one whose hold has already expired, say nothing.
  await expect(card("free")).not.toContainText(/Paced/);
  await expect(card("expired")).not.toContainText(/Paced/);

  // The override: Apply is offered, enabled, and labelled so it does not look
  // like it will bounce off the limit.
  const applyHeld = card("held-day").getByRole("button", { name: /Apply anyway/ });
  await expect(applyHeld).toBeEnabled();
  await expect(card("free").getByRole("button", { name: /^Apply →/ })).toBeEnabled();

  await applyHeld.click();
  await expect
    .poll(() => applied, { message: "clicking Apply on a paced job must still send it" })
    .toEqual([expect.stringContaining("held-day/preflight-approve")]);
});
