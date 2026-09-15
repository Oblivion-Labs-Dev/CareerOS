import {test,expect} from "@playwright/test";
const pages=[{path:"/applications",name:"autopilot"},{path:"/applications?tab=applications",name:"applications"},{path:"/applications?tab=inbox",name:"inbox"},{path:"/applications?tab=pipeline",name:"pipeline"},{path:"/dashboard",name:"dashboard"},{path:"/jobs/discover",name:"browse"},{path:"/profile",name:"profile"},{path:"/settings",name:"settings"},{path:"/diagnostic",name:"diagnostic"}];
for(const route of pages)test(`compact ${route.name} workspace`,async({page})=>{
 const failures:string[]=[];page.on("pageerror",error=>failures.push(error.message));
 await page.route("**/api/backend/**",r=>r.fulfill({status:503,json:{detail:"Layout test: service unavailable"}}));
 await page.route("**/api/backend/tracker/pipeline",r=>r.fulfill({json:{total:2,ghostThresholdDays:21,funnel:[],columns:[{key:"applied",label:"Applied",items:[{id:"one",companyName:"Acme",roleTitle:"Engineer",daysSinceActivity:2}]},{key:"interviewing",label:"Interviewing",items:[{id:"two",companyName:"Orbit",roleTitle:"Designer",daysSinceActivity:1}]}]}}));
 await page.route("**/api/backend/email/recruiter-threads/classified?*",r=>r.fulfill({json:{success:true,count:1,categoryCounts:{interview:1},threads:[{uid:"one",fromName:"Recruiter",fromAddress:"recruiter@example.com",subject:"Interview invitation",snippet:"Choose a time to meet the team.",date:"2026-09-12",category:"interview",categoryLabel:"Interview"}]}}));
 await page.goto(route.path);await expect(page.locator("h1").first()).toBeAttached();
 await expect(page.getByText("Your job search agent",{exact:true})).toHaveCount(0);await expect(page.getByText("Let’s reconnect.",{exact:true})).toHaveCount(0);
 if(route.name==="applications")await expect(page.locator("#night-batch")).toHaveCount(0);
 if(route.name==="autopilot")await expect(page.locator("#night-batch")).toBeVisible();
 if(["profile","settings"].includes(route.name))await expect(page.getByRole("heading",{level:1}).first()).toBeVisible();
 await page.screenshot({path:`test-results/compact-${route.name}.png`});
 await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:"reduce"});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
 expect(failures).toEqual([]);
});
