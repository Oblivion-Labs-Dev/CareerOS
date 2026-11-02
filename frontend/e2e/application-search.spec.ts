import { expect, test } from "@playwright/test";

/**
 * The Applications search must query the server across every row, and answer
 * from the cached job list fast enough to type into.
 *
 * Both halves matter and neither is obvious from the UI. If the search ever
 * regressed to filtering only the rows already fetched, a job further down a
 * 950-row list would silently become unfindable by name — it would just look
 * like the job was not there. And if the read path stopped being served from
 * the background-refreshed cache, every keystroke would re-parse the whole
 * table and the box would feel broken rather than wrong.
 */

const MAX_ROUND_TRIP_MS = 600;

test("search queries the server and answers from cache @local", async ({ page }) => {
  test.setTimeout(240_000);

  const queries: string[] = [];
  const timings: number[] = [];
  const pending = new Map<string, number>();

  page.on("request", (r) => {
    if (r.url().includes("/autopilot/jobs?")) pending.set(r.url(), Date.now());
  });
  page.on("response", (r) => {
    const started = pending.get(r.url());
    if (started === undefined) return;
    const qs = decodeURIComponent(r.url().split("?")[1] || "");
    if (qs.includes("search=")) {
      queries.push(qs);
      timings.push(Date.now() - started);
    }
  });

  await page.goto("/applications?tab=applications", { waitUntil: "domcontentloaded" });
  const search = page.getByPlaceholder(/Search company/i);
  await search.waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForTimeout(3000);
  queries.length = 0;
  timings.length = 0;

  for (const q of ["Anthropic", "engineer", "Seattle"]) {
    await search.fill(q);
    await page.waitForTimeout(2500);
  }

  // The term reaches the server, and no status filter is imposed on it — so
  // the search covers every bucket, not just the one on screen.
  expect(queries.length, "search should hit the server").toBeGreaterThan(0);
  expect(queries.some((q) => /search=Anthropic/i.test(q))).toBeTruthy();
  expect(queries.every((q) => !q.includes("status=")), "search must span every bucket").toBeTruthy();

  const median = [...timings].sort((a, b) => a - b)[Math.floor(timings.length / 2)];
  console.log(`search round trips: ${timings.join(", ")} ms (median ${median})`);
  expect(median, "search should be served from cache").toBeLessThan(MAX_ROUND_TRIP_MS);
});
