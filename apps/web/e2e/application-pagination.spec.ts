import { expect, test } from "@playwright/test";

test("application filters fetch twenty records and append on scroll @local", async ({ page }) => {
  const requests: URL[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.endsWith("/autopilot/jobs")) requests.push(url);
  });
  await page.goto("/applications?tab=applications");
  const cards = page.locator("article[data-job-id]");
  await expect(cards).toHaveCount(20, { timeout: 20000 });
  // Two summary widgets share this endpoint on purpose: the control-center
  // sample (limit=100, facets=false, feeds last activity and queue scores) and
  // Recent submissions (limit=3). Every other request is the list itself and
  // must page at twenty.
  const SUMMARY_LIMITS = new Set(["100", "3"]);
  const listRequests = () => requests.filter(url => !SUMMARY_LIMITS.has(url.searchParams.get("limit") ?? ""));
  expect(listRequests().length).toBeGreaterThan(0);
  expect(listRequests().every(url => url.searchParams.get("limit") === "20")).toBe(true);
  const firstId = await cards.first().getAttribute("data-job-id");
  await page.getByRole("button", { name: "Load 20 more" }).scrollIntoViewIfNeeded();
  await expect(cards).toHaveCount(40, { timeout: 20000 });
  expect(requests.some(url => url.searchParams.get("offset") === "20")).toBe(true);
  await expect(cards.first()).toHaveAttribute("data-job-id", firstId!);
  for (const [label, status] of [["Queued", "queued"], ["Skipped", "skipped"], ["Ineligible", "ineligible"]]) {
    await page.getByRole("button", { name: new RegExp(`^${label} \\d`) }).click();
    await expect(cards.first()).toHaveAttribute("data-status", status, { timeout: 20000 });
    const filtered = requests.filter(url => (url.searchParams.get("status") ?? "").toLowerCase().split(",").includes(status) && url.searchParams.get("limit") !== "100");
    expect(filtered.length).toBeGreaterThan(0);
    expect(filtered.every(url => url.searchParams.get("limit") === "20")).toBe(true);
    const count = await cards.count();
    expect(count).toBeLessThanOrEqual(20);
    expect(await cards.evaluateAll(elements => new Set(elements.map(element => element.getAttribute("data-job-id"))).size)).toBe(count);
  }
});
