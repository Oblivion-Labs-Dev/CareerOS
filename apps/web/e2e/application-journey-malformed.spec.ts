import { expect, test } from "@playwright/test";

/**
 * Regression: a journey payload without `assessment` (an older backend, or a
 * proxy error page that still parses as JSON) used to throw while rendering and
 * take the whole Applications page down. The panel must show its own error
 * state and leave the rest of the dossier usable.
 *
 * Every API call is a local fixture.
 */
test("a malformed journey shows the panel's error, not a crashed page", async ({ page, baseURL }) => {
  const now = new Date().toISOString();
  const job = { id: "journey-bad", company: "Globex", title: "Staff Engineer", location: "Remote", status: "SUBMITTED", matchScore: 88, updatedAt: now, applicationUrl: `${baseURL}/fixture` };
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().addCookies([{ name: "co_session", value: "isolated-ui-fixture", url: baseURL! }]);
  await page.addInitScript(() => window.localStorage.setItem("careeros.cardStyle", "classic"));
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() !== "GET") return route.fulfill({ json: { success: true } });
    if (url.pathname.endsWith("/autopilot/jobs")) {
      return route.fulfill({ json: { success: true, jobs: [job], total: 1, hasMore: false, statusCounts: { SUBMITTED: 1 }, companyCounts: {}, titleCounts: {} } });
    }
    if (url.pathname.endsWith("/autopilot/stats")) {
      return route.fulfill({ json: { success: true, statusCounts: { SUBMITTED: 1 }, uiCounts: {}, companyCountsByStatus: {}, titleCountsByStatus: {} } });
    }
    // Parses as JSON and has events, but no assessment.
    if (url.pathname.endsWith("/journey")) return route.fulfill({ json: { success: true, jobId: job.id, events: [], evidence: [] } });
    if (url.pathname.endsWith("/auth/status")) return route.fulfill({ json: { authRequired: false } });
    return route.fulfill({ json: { success: true, state: { status: "IDLE", workers: [] }, jobs: [], items: [], events: [], settings: {}, profile: {}, preferences: {} } });
  });

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=submitted");
  const card = page.getByRole("button", { name: `Open details for ${job.title} at ${job.company}` });
  await expect(card).toBeVisible({ timeout: 60_000 });
  await card.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Journey", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Could not load this application's evidence.");
  await expect(dialog.getByRole("button", { name: "Overview", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
