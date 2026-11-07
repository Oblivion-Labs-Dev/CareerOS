import { expect, test, type Page } from "@playwright/test";

/**
 * The Lab flip look for application cards, the only card look. A click flips
 * the card open into a centred popup that explains where it stands, with its
 * actions: Apply still sends, and an unscored job shows a dash rather than a
 * made-up number.
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

test("Lab is the only application card, even with an old Classic choice saved", async ({ page, baseURL }) => {
  await mockApi(page, baseURL!, []);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");
  await expect(card(page, "lab-queued")).toBeVisible({ timeout: 60_000 });
  await expect(card(page, "lab-queued")).toHaveAttribute("data-card-variant", "lab");
  // Regression: readiness without a questions block used to crash the whole
  // page under Lab; the tile now says the count is unknown.
  await expect(page.getByText("Blocking questions unknown")).toHaveCount(1);
  // Regression: with no batch run recorded, Recent Activity said "Nothing has
  // run yet." right above the failed application it was showing.
  const activity = page.getByRole("complementary", { name: "Recent Activity" });
  await expect(activity).toContainText("Initech");
  await expect(activity).not.toContainText("Nothing has run yet");

  // The Classic/Lab switch is gone, and a Classic choice saved by an older
  // build no longer brings the old cards back.
  await expect(page.getByRole("radiogroup", { name: "Metric card style" })).toHaveCount(0);
  await page.evaluate(() => window.localStorage.setItem("careeros.cardStyle", "classic"));
  await page.reload();
  await expect(card(page, "lab-queued")).toBeVisible({ timeout: 60_000 });
  await expect(card(page, "lab-queued")).toHaveAttribute("data-card-variant", "lab");
  await expect(page.locator("html")).toHaveAttribute("data-material", "matte");
});

test("Settings no longer offers the retired application card styles", async ({ page, baseURL }) => {
  await mockApi(page, baseURL!, []);
  await page.goto("/settings");
  await expect(page.locator("main")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { name: "Application card style" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Holographic|Heritage|Clay/ })).toHaveCount(0);
});

test("Lab cards sit flat in the grid and a click flips open the details popup", async ({ page, baseURL }) => {
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

  // Regression: the shared KPI hover-slide pushed the old back face out of
  // the card, leaving a stray column beside the grid. Cards are front-only now
  // and nothing inside one may spill past its edge.
  const spills = await page.locator('article[data-card-variant="lab"]').evaluateAll(cards =>
    cards.flatMap(card => {
      const box = card.getBoundingClientRect();
      return [...card.querySelectorAll("*")]
        .map(el => el.getBoundingClientRect())
        .filter(r => r.width > 0 && (r.right > box.right + 1 || r.left < box.left - 1))
        .map(() => card.getAttribute("data-job-id"));
    }));
  expect(spills).toEqual([]);

  // Hover no longer turns the card over: nothing rotates.
  await queued.hover();
  const rotated = await queued.evaluate(el =>
    [el, ...el.querySelectorAll("*")].some(n => getComputedStyle(n).transform.startsWith("matrix3d")));
  expect(rotated).toBe(false);

  // A click flips open a centred popup, not the right-hand side panel.
  await queued.click({ position: { x: 20, y: 20 } });
  const dialog = page.locator(".aa-flip-dialog");
  await expect(dialog).toBeVisible();
  await expect(page.locator(".aa-wizard-panel")).toHaveCount(0);
  const summary = dialog.getByRole("region", { name: "Where this application stands" });
  await expect(summary).toContainText("Ready to send");
  const facts = summary.locator("dl");
  await expect(facts).toContainText("91% · Excellent match");
  await expect(facts).toContainText("Go, Kubernetes, Postgres +1");
  await expect(facts).toContainText("Rust");
  await expect(facts).toContainText("$180k–$210k");
  await expect(dialog.getByRole("region", { name: "Application summary" })).toBeVisible();

  // Apply inside the popup still sends.
  await summary.getByRole("button", { name: /^Apply →/ }).click();
  await expect.poll(() => applied).toEqual([expect.stringContaining("lab-queued/preflight-approve")]);

  // Escape flips it back into the card, which is visible again afterwards.
  // Regression: the details used to unmount the instant the dialog closed, so
  // it flipped back into the card as a blank shell. The content stays for the
  // whole way home.
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveAttribute("data-state", "closed");
  expect((await dialog.locator(".aa-flip-face").innerText()).trim()).not.toBe("");
  await expect(dialog).toHaveCount(0);
  await expect(queued).toBeVisible();
  await expect(queued).toHaveCSS("visibility", "visible");

  // The failure is explained from the stored error, not a guess.
  await card(page, "lab-failed").press("Enter");
  const failed = page.locator(".aa-flip-dialog").getByRole("region", { name: "Where this application stands" });
  await expect(failed).toContainText("Couldn't finish sending");
  await expect(failed).toContainText("Upload field never appeared");
  await expect(failed.locator("dt")).toHaveText(["Match"]);
  await expect(failed.getByRole("button", { name: /Retry/ })).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(page.locator(".aa-flip-dialog")).toHaveCount(0);
});

test("Opening a card flips its details up; only the theme switch reveals in a circle", async ({ page, baseURL }) => {
  await mockApi(page, baseURL!, []);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/applications?tab=applications");
  await expect(card(page, "lab-queued")).toBeVisible({ timeout: 60_000 });

  // Regression: the theme's circular reveal was bound to every view
  // transition, so opening the dossier played as an expanding circle.
  const opening = await animationsAfter(page, 'article[data-job-id="lab-unscored"]');
  expect(opening).not.toContain("theme-reveal");
  await expect(page.locator(".aa-flip-dialog")).toBeVisible();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  const theming = await animationsAfter(page, 'button[aria-label^="Switch to"]');
  expect(theming).toContain("theme-reveal");
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
