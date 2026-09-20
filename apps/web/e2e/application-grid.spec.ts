import { expect, test } from "@playwright/test";

test("card grid filters the server, pages, searches and preserves review actions", async ({ page, baseURL }) => {
  // Page middleware checks presence only; every API call below is a local fixture.
  await page.context().addCookies([{name:"co_session",value:"isolated-ui-fixture",url:baseURL!}]);
  const statuses = ["NEEDS_REVIEW", "STAGED", "MANUAL_REVIEW", "FAILED", "DISCOVERED", "SCORED", "QUEUED", "APPLYING", "SUBMITTED", "REJECTED", "SKIPPED", "INELIGIBLE"];
  const records = Array.from({ length: 1200 }, (_, i) => ({id:`fixture-${i}`, company:i === 1199 ? "Faraway" : `Company ${i}`, title:"Senior Software Engineer", location:"Seattle, WA", status:statuses[i % statuses.length], matchScore:85 + i % 10, updatedAt:new Date().toISOString(), resumeFileUsed:i % 2 ? "approved.pdf" : undefined, submissionConfirmed:false, applicationUrl:"https://example.invalid/job", lastError:i % 12 === 2 ? "This application needs your attention." : undefined}));
  const statusCounts = Object.fromEntries(statuses.map(status => [status,100]));
  const requests: URL[] = [], mutations: string[] = [], errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url());
    if(request.method() !== "GET") {mutations.push(url.pathname);return route.fulfill({json:{success:true}});}
    if(url.pathname.endsWith("/autopilot/jobs")) {
      requests.push(url);
      const selected = url.searchParams.get("status")?.split(","), query = url.searchParams.get("search")?.toLowerCase() || "";
      const rows = records.filter(record => (!selected || selected.includes(record.status)) && `${record.company} ${record.title} ${record.location}`.toLowerCase().includes(query));
      const offset=Number(url.searchParams.get("offset") || 0), limit=Number(url.searchParams.get("limit") || 24);
      return route.fulfill({json:{success:true,jobs:rows.slice(offset,offset+limit),total:rows.length,hasMore:offset+limit<rows.length,statusCounts,companyCounts:Object.fromEntries(rows.map(row=>[row.company,1])),titleCounts:{"Senior Software Engineer":rows.length}}});
    }
    if(url.pathname.endsWith("/autopilot/stats")) return route.fulfill({json:{success:true,statusCounts,uiCounts:{},companyCountsByStatus:{},titleCountsByStatus:{}}});
    if(url.pathname.endsWith("/auth/status")) return route.fulfill({json:{authRequired:false}});
    return route.fulfill({json:{success:true,state:{status:"IDLE",workers:[]},jobs:[],items:[],events:[],settings:{},profile:{},preferences:{}}});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto("/applications?tab=applications");
  const views=page.getByRole("navigation",{name:"Application status",exact:true}), cards=page.locator("article[data-job-id]");
  await expect(cards.first()).toBeVisible({timeout:60000});
  await expect(views.getByRole("button",{name:/Manual Review/})).toContainText("100");
  await views.getByRole("button",{name:/Manual Review/}).click();
  await expect.poll(()=>requests.filter(url=>url.searchParams.get("limit")==="24").at(-1)?.searchParams.get("status")).toBe("MANUAL_REVIEW");
  await expect(cards.first()).toHaveAttribute("data-status","manual");
  await expect(cards.first().getByRole("button",{name:"Autofill & open"})).toBeVisible();
  await cards.first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await views.getByRole("button",{name:/Submitted/}).click();
  await expect.poll(()=>requests.filter(url=>url.searchParams.get("limit")==="24").at(-1)?.searchParams.get("status")).toBe("SUBMITTED,REJECTED");
  await page.getByRole("navigation",{name:"Submitted breakdown"}).getByRole("button",{name:/Rejected/}).click();
  await expect(cards.first()).toHaveAttribute("data-status","rejected");
  await page.getByRole("button",{name:"Load 24 more"}).scrollIntoViewIfNeeded();
  await expect.poll(()=>cards.count()).toBeGreaterThanOrEqual(48);
  expect(requests.some(url=>url.searchParams.get("offset")==="24")).toBeTruthy();
  await views.getByRole("button",{name:/All applications/}).click();
  await page.getByRole("searchbox",{name:"Search applications"}).fill("Faraway");
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Faraway");
  await page.getByRole("searchbox",{name:"Search applications"}).fill("");
  await views.getByRole("button",{name:/In Review/}).click();
  await expect(cards.first()).toHaveAttribute("data-status","review");
  await page.getByRole("region",{name:"Application filters"}).evaluate(el=>el.scrollIntoView({block:"start",behavior:"instant"}));
  await page.screenshot({path:"test-results/application-grid-desktop.png",fullPage:false});
  for(const width of [390,320]) {
    await page.setViewportSize({width,height:844});
    expect(await page.getByRole("region",{name:"Application filters"}).evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
    expect(await cards.first().evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
  }
  await page.getByRole("region",{name:"Application filters"}).evaluate(el=>el.scrollIntoView({block:"start",behavior:"instant"}));
  await page.screenshot({path:"test-results/application-grid-mobile.png",fullPage:false});
  expect(mutations).toEqual([]);
  expect(errors).toEqual([]);
});
