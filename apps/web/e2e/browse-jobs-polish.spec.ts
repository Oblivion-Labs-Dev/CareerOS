import {expect,test} from "@playwright/test";

test("browse cards, search, selection and responsive themes",async({page})=>{
  let scrapeCalls=0;
  await page.route("**/api/backend/jobs/discover**",async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith("/scrape")){scrapeCalls++;return route.fulfill({json:{success:true}});}
    if(url.pathname.endsWith("/filter-options"))return route.fulfill({json:{titles:["Senior Platform Engineer","Backend Engineer","Staff Engineer"],companies:["Acme","Orbit","North"],specialties:[{value:"swe",label:"Software Engineering"}],seniorities:["senior","staff","unspecified"],workModes:["remote","unspecified"],experience:["unspecified"]}});
    if(url.pathname.endsWith("/stats"))return route.fulfill({json:{totalJobs:3,indexedCompanies:3,strongMatch:1,moderateMatch:1,fresh48h:2}});
    if(url.pathname.endsWith("/locations"))return route.fulfill({json:{locations:[]}});
    if(url.pathname.endsWith("/status"))return route.fulfill({json:{success:true,running:false}});
    if(!url.pathname.endsWith("/jobs/discover"))return route.continue();
    if(!url.search)return route.continue();
    const n=Number(url.searchParams.get("page")||1);
    return route.fulfill({json:{success:true,total:3,indexedTotal:3,page:n,perPage:2,totalPages:2,jobs:n===1 ? [
      {id:"browse-1",companyName:"Acme",title:"Senior Platform Engineer",location:"Seattle, WA",url:"https://example.com/job",relevancyScore:88,color:"green",keywordsMatched:["Python","Systems","Cloud"],freshness:{label:"Listed today",hours_ago:1},salaryRange:"$160k–$200k"},
      {id:"browse-2",companyName:"Orbit",title:"Backend Engineer",location:"Remote",url:"https://example.com/second",relevancyScore:null,keywordsMatched:[]},
    ]:[{id:"browse-3",companyName:"North",title:"Staff Engineer",location:"New York",url:"https://example.com/third",relevancyScore:66,keywordsMatched:["Go"]}]}});
  });
  await page.goto("/jobs/discover");
  await expect(page.getByRole("heading",{name:"Browse jobs",exact:true})).toBeVisible();
  const first=page.locator('article[data-job-id="browse-1"]');
  await expect(first).toBeVisible();
  await expect(first.getByText("Strong profile fit",{exact:true})).toBeVisible();
  await expect(page.getByText("Awaiting score",{exact:true})).toBeVisible();
  await expect(page.getByText("12% gap",{exact:false})).toHaveCount(0);
  await first.getByRole("button",{name:/Add to shortlist/}).click();
  await expect(first.getByRole("button",{name:/Remove from shortlist/})).toHaveAttribute("aria-pressed","true");
  await first.getByRole("checkbox").check();
  await expect(first).toHaveAttribute("data-selected","true");
  await page.getByRole("button",{name:/Show 3 results/}).click();
  await expect(first).toBeVisible();expect(scrapeCalls).toBe(0);
  await page.locator('[class*="browse-jobs_grid"]').screenshot({path:"test-results/browse-cards-dark.png"});
  await page.getByRole("button",{name:"Next →",exact:true}).click();
  await expect(page.getByRole("heading",{name:/Staff Engineer/})).toBeVisible();
  await page.getByRole("button",{name:"← Previous",exact:true}).click();
  await expect(first).toBeVisible();
  await expect(first.getByRole("checkbox")).not.toBeChecked();
  const light=page.getByRole("button",{name:"Switch to Light Mode",exact:true});if(await light.isVisible())await light.click();
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:"reduce"});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await first.screenshot({path:"test-results/browse-card-mobile.png"});
});
