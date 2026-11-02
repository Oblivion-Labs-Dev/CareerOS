import {expect,test} from "@playwright/test";

test("dashboard backend metrics and chart drilldowns", async ({page}) => {
  const response = await page.request.get("/api/backend/tracker/summary");
  expect(response.ok()).toBeTruthy();
  const {outcomes} = await response.json();
  expect(outcomes.totalSubmitted).toBeGreaterThanOrEqual(outcomes.awaitingConfirmation);
  await page.goto("/dashboard");
  await expect(page.getByText("Recorded submissions",{exact:true})).toBeVisible();
  await expect(page.getByText("Outcome coverage:",{exact:false})).toBeVisible();
  const chart = page.getByRole("region",{name:"Application activity"});
  await chart.getByRole("button",{name:"responses",exact:true}).click();
  await expect(chart.getByRole("button",{name:/responses on/})).toHaveCount(14);
  await chart.getByRole("button",{name:/responses on/}).last().click();
  await expect(page.getByText(/recorded responses/)).toBeVisible();
  await page.screenshot({path:"test-results/outcomes-dashboard.png",fullPage:true});
  const theme = page.getByRole("button",{name:"Switch to Light Mode",exact:true});
  if (await theme.isVisible()) await theme.click();
  await page.screenshot({path:"test-results/outcomes-dashboard-light.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.emulateMedia({reducedMotion:"reduce"});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1)).toBe(true);
  await page.screenshot({path:"test-results/outcomes-dashboard-mobile.png",fullPage:true});
});

test("card depth respects motion and dashboard links open exact jobs", async ({page}) => {
  const response = await page.request.get("/api/backend/application-assistant/autopilot/jobs?status=SUBMITTED&limit=1");
  const {jobs} = await response.json();
  test.skip(!jobs?.length,"No submitted record available");
  await page.goto(`/applications?tab=submitted&job=${encodeURIComponent(jobs[0].id)}`);
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("heading",{name:jobs[0].company,exact:true})).toBeVisible();
  await page.keyboard.press("Escape");
  const card=page.locator("article[data-job-id]").first();
  await card.hover();
  await page.emulateMedia({reducedMotion:"reduce"});
  await expect(card).toHaveCSS("transform","none");
});
