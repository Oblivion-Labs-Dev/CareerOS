import { expect, test } from "@playwright/test";

// The dashboard tab once fetched /tracker/summary twice, paged every full job
// row through /autopilot/jobs at limit=1000 for its Insights and Search
// Intelligence panels, showed invented numbers ("100% Success", "DocuSign"),
// and its sub-tab hover hard-coded white text that vanished on the light theme.
test("dashboard loads lean, shows no invented numbers, and tabs stay readable in light mode @local", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("theme", "light"));
  const requests: URL[] = [];
  page.on("request", request => requests.push(new URL(request.url())));
  await page.goto("/applications?tab=dashboard");
  await expect(page.getByRole("tab", { name: "Search Intelligence" })).toBeVisible({ timeout: 20000 });
  for (const invented of ["100% Success", "DocuSign", "US Citizen"]) await expect(page.getByText(invented)).toHaveCount(0);

  const insightsTab = page.getByRole("tab", { name: "Outcomes & Audit History" });
  await insightsTab.click();
  await expect(page.getByText("Outcome mix")).toBeVisible({ timeout: 20000 });
  await insightsTab.hover();
  const [color, background] = await insightsTab.evaluate(el => [getComputedStyle(el).color, getComputedStyle(document.body).backgroundColor]);
  expect(color).not.toBe(background);
  expect(color).not.toBe("rgb(255, 255, 255)");

  await page.getByRole("tab", { name: "Search Intelligence" }).click();
  await expect(page.getByText(/All [\d,]+ application records/)).toBeVisible({ timeout: 20000 });

  expect(requests.filter(url => url.pathname.endsWith("/tracker/summary")).length).toBe(1);
  expect(requests.filter(url => url.pathname.endsWith("/autopilot/jobs") && url.searchParams.get("limit") === "1000")).toHaveLength(0);
  expect(requests.filter(url => url.pathname.endsWith("/autopilot/jobs/insight-rows")).length).toBeGreaterThan(0);
});
