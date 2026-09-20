import { expect, test } from "@playwright/test";

/**
 * Loading states are shaped like the content that is coming.
 *
 * There are two separate waits in this app and they need different mechanisms —
 * a distinction the first version of this work got wrong:
 *
 *   route transition  -> `loading.tsx`, rendered by Next between segments
 *   data fetch        -> the component's own `loading` state
 *
 * Every page here is a client component that renders immediately and fetches in
 * `useEffect`, so nothing suspends and `loading.tsx` is gone almost at once.
 * The wait people actually feel is the second one, and these assert that one:
 * the backend is held open, the skeleton is asserted while it is on screen,
 * then released.
 *
 * Only the health check is allowed through — blocking it too makes the app
 * report "Backend offline" and render an error state instead of a loading one,
 * which is what the first version of this spec accidentally measured.
 */

test("the dashboard shows content-shaped placeholders while matches load @skeleton", async ({ page }) => {
  let release: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });

  await page.route("**/api/backend/**", async (route) => {
    if (route.request().url().includes("/health")) {
      await route.continue();
      return;
    }
    await held;
    await route.continue();
  });

  await page.goto("/dashboard");

  const pending = page.getByRole("status", { name: "Loading matches" });
  await expect(pending, "the data wait should be shown, not a bare text line").toBeVisible({
    timeout: 20_000,
  });
  await expect(pending).toHaveAttribute("aria-busy", "true");

  const blocks = pending.locator(".skeleton");
  expect(
    await blocks.count(),
    "a placeholder should stand in for the cards, so the grid does not resize when they arrive",
  ).toBeGreaterThan(2);

  release?.();
  await expect(pending).toBeHidden({ timeout: 30_000 });
});

/**
 * The other workspaces, each shaped like what it renders.
 *
 * One test per page rather than one loop over all of them: they mount
 * different components with different data calls, and a shared loop would
 * report "the pages are fine" while quietly skipping the one that never
 * reached its loading branch.
 */
const WORKSPACES: { path: string; label: string; minBlocks: number }[] = [
  { path: "/applications?tab=applications", label: "Loading applications…", minBlocks: 6 },
  { path: "/jobs/discover", label: "Finding your next opportunity…", minBlocks: 6 },
];

for (const { path, label, minBlocks } of WORKSPACES) {
  test(`${path} shows a content-shaped placeholder while it loads @skeleton`, async ({ page }) => {
    let release: (() => void) | undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });

    await page.route("**/api/backend/**", async (route) => {
      const url = route.request().url();
      // Health and auth must answer, or the app renders an offline/login state
      // rather than a loading one — that is an error path, not this test.
      if (url.includes("/health") || url.includes("/auth/")) {
        await route.continue();
        return;
      }
      await held;
      await route.continue();
    });

    await page.goto(path);

    const pending = page.getByRole("status", { name: label });
    await expect(pending).toBeVisible({ timeout: 20_000 });
    await expect(pending).toHaveAttribute("aria-busy", "true");
    expect(
      await pending.locator(".skeleton").count(),
      "the placeholder should stand in for the real content, not shrink to a line",
    ).toBeGreaterThanOrEqual(minBlocks);

    release?.();
  });
}

test("placeholders do not animate when motion is reduced @skeleton", async ({ browser }) => {
  // The block still renders — the information is in the shape, not the sheen.
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  try {
    await page.route("**/api/backend/**", async (route) => {
      if (route.request().url().includes("/health")) {
        await route.continue();
        return;
      }
      await new Promise(() => {});
    });
    await page.goto("/dashboard");

    const block = page.locator(".skeleton").first();
    await expect(block).toBeVisible({ timeout: 20_000 });

    const animation = await block.evaluate((el) => getComputedStyle(el).animationName);
    expect(animation, "the sheen must be opt-in behind prefers-reduced-motion").toBe("none");
  } finally {
    await context.close();
  }
});
