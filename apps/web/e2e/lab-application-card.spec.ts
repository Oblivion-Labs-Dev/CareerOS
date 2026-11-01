import { expect, test, type Page } from "@playwright/test";

/**
 * The Lab flip look for application cards. Lab is the default; Classic stays
 * reachable through the Classic/Lab switch. Each job card turns on hover to show
 * why it is where it is plus its actions, and must keep every Classic
 * behaviour: a click opens the dossier, Apply still sends, and an unscored job
 * shows a dash rather than a made-up number.
 *
 * Every API call is a local fixture, so nothing is ever really applied to.
 */

function jobs(baseURL: string) {
  const now = new Date().toISOString();
  return [
    { id: "lab-queued", company: "Globex", title: "Staff Engineer", location: "Remote", status: "QUEUED", matchScore: 91, keyMatchingSkills: ["Go", "Kubernetes", "Postgres", "gRPC"], missingSkills: ["Rust"], salary: "$180k–$210k", updatedAt: now, applicationUrl: `${baseURL}/fixture` },
    { id: "lab-failed", company: "Initech", title: "Platform Engineer", location: "Austin, TX", status: "FAILED", matchScore: 77, lastError: "Upload field never appeared", updatedAt: now, applicationUrl: `${baseURL}/fixture` },
    { id: "lab-unscored", company: "Umbrella", title: "Backend Engineer", location: "Remote", status: "QUEUED", updatedAt: now, applicationUrl: `${baseURL}/fixture` },
  ];
}

async function mockApi(page: Page, baseURL: string, applied: string[]) {
  const rows = jobs(baseURL);
  await page.context().addCookies([{ name: "co_session", value: "isolated-ui-fixture", url: baseURL }]);
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== "GET") {
      if (url.pathname.includes("preflight-approve")) applied.push(url.pathname);
      return route.fulfill({ json: { success: true } });
    }
    if (url.pathname.endsWith("/autopilot/jobs")) {
      return route.fulfill({
        json: { success: true, jobs: rows, total: rows.length, hasMore: false, statusCounts: { QUEUED: 2, FAILED: 1 }, companyCounts: {}, titleCounts: {} },
      });
    }
    if (url.pathname.endsWith("/autopilot/stats")) {
      return route.fulfill({ json: { success: true, statusCounts: { QUEUED: 2, FAILED: 1 }, uiCounts: {}, companyCountsByStatus: {}, titleCountsByStatus: {} } });
    }
    // No journey recorded yet; the catch-all body below is not a journey.
    if (url.pathname.endsWith("/journey")) return route.fulfill({ status: 404, json: { detail: "Not found" } });
    if (url.pathname.endsWith("/auth/status")) return route.fulfill({ json: { authRequired: false } });
    return route.fulfill({ json: { success: true, state: { status: "IDLE", workers: [] }, jobs: [], items: [], events: [], settings: {}, profile: {}, preferences: {} } });
  });
}

const card = (page: Page, id: string) => page.locator(`article[data-job-id="${id}"]`);

test("Lab is the default application card; Classic is still a saved choice", async ({ page, baseURL }) => {
  await mockApi(page, baseURL!, []);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");
  await expect(card(page, "lab-queued")).toBeVisible({ timeout: 60_000 });
  await expect(card(page, "lab-queued")).toHaveAttribute("data-card-variant", "lab");
  // Regression: readiness without a questions block used to crash the whole
  // page under Lab; the tile now says the count is unknown.
  await expect(page.getByText("Blocking questions unknown")).toHaveCount(1);

  await page.evaluate(() => window.localStorage.setItem("careeros.cardStyle", "classic"));
  await page.reload();
  await expect(card(page, "lab-queued")).toBeVisible({ timeout: 60_000 });
  await expect(card(page, "lab-queued")).not.toHaveAttribute("data-card-variant", "lab");
});

test("Settings no longer offers the retired application card styles", async ({ page, baseURL }) => {
  await mockApi(page, baseURL!, []);
  await page.goto("/settings");
  await expect(page.locator("main")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Application card style" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Holographic|Heritage|Clay/ })).toHaveCount(0);
});

test("Lab application cards flip, keep their actions and open the dossier", async ({ page, baseURL }) => {
  const applied: string[] = [];
  await mockApi(page, baseURL!, applied);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");

  const queued = card(page, "lab-queued");
  await expect(queued).toBeVisible({ timeout: 60_000 });
  await expect(queued).toHaveAttribute("data-card-variant", "lab");
  await expect(queued).toHaveAttribute("data-accent", "blue");
  await expect(card(page, "lab-failed")).toHaveAttribute("data-accent", "orange");

  // Real score as clay digits; an unscored job shows a dash, never a number.
  await expect(queued.getByLabel("91% match")).toBeVisible();
  await expect(card(page, "lab-unscored").getByLabel("Not scored")).toContainText("—");

  // The back explains the failure from the stored error, not a guess.
  await expect(card(page, "lab-failed")).toContainText("Upload field never appeared");
  await expect(card(page, "lab-failed").getByRole("button", { name: /Retry/ })).toHaveCount(1);

  // The back speaks plainly and lists only facts the job really has.
  const queuedBack = queued.locator("dl");
  await expect(queued).toContainText("Ready to send");
  await expect(queuedBack).toContainText("91% · Excellent match");
  await expect(queuedBack).toContainText("Go, Kubernetes, Postgres +1");
  await expect(queuedBack).toContainText("Rust");
  await expect(queuedBack).toContainText("$180k–$210k");
  await expect(card(page, "lab-failed")).toContainText("Couldn't finish sending");
  await expect(card(page, "lab-failed").locator("dt")).toHaveText(["Match"]);
  await expect(card(page, "lab-unscored").locator("dl")).toHaveCount(0);

  // Hover turns the card: the front rotates away.
  const frontTransform = () => queued.locator("> div").first().evaluate(el => getComputedStyle(el).transform);
  await page.mouse.move(0, 0);
  const resting = await frontTransform();
  await queued.hover();
  await expect.poll(frontTransform, { message: "front face should rotate on hover" }).not.toBe(resting);

  // Apply on the back still sends, and does not also open the dossier.
  await queued.getByRole("button", { name: /^Apply →/ }).click();
  await expect.poll(() => applied).toEqual([expect.stringContaining("lab-queued/preflight-approve")]);
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // A click on the card body opens the dossier, exactly like Classic.
  await card(page, "lab-unscored").click({ position: { x: 20, y: 20 } });
  await expect(page.getByRole("dialog").getByRole("region", { name: "Application summary" })).toBeVisible();
});

/**
 * Every CSS animation name seen during the first second after clicking
 * `selector`. Sampled each frame, because a view transition swaps the DOM a
 * few frames late and a single early snapshot misses what follows.
 */
async function animationsAfter(page: Page, selector: string) {
  return page.evaluate(async (sel) => {
    const seen = new Set<string>();
    (document.querySelector(sel) as HTMLElement).click();
    const end = performance.now() + 1000;
    while (performance.now() < end) {
      for (const a of document.getAnimations()) seen.add((a as CSSAnimation).animationName ?? "");
      await new Promise(resolve => requestAnimationFrame(resolve));
    }
    return [...seen];
  }, selector);
}

test("the dossier slides in; only the theme switch reveals in a circle", async ({ page, baseURL }) => {
  await mockApi(page, baseURL!, []);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");
  await expect(card(page, "lab-queued")).toBeVisible({ timeout: 60_000 });

  // Regression: the theme's circular reveal was bound to every view
  // transition, so opening the dossier played as an expanding circle.
  const opening = await animationsAfter(page, 'article[data-job-id="lab-unscored"]');
  expect(opening).toContain("aa-wizard-panel-in");
  expect(opening).not.toContain("theme-reveal");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  const theming = await animationsAfter(page, 'button[aria-label^="Switch to"]');
  expect(theming).toContain("theme-reveal");
});
