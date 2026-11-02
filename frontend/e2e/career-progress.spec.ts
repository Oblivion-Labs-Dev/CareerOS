import {expect,test} from "@playwright/test";

const initial = () => ({week:"2026-09-07",preferences:{weeklyGoal:2,timezone:"UTC"},completedCount:0,goalReached:false,player:{name:"Alex Morgan",specialty:"Senior Software Engineer"},quests:[
  {id:"resume",title:"Polish your story",detail:"Review one resume achievement.",href:"/profile",action:"Open resume & profile",symbol:"✦",completedAt:null},
  {id:"shortlist",title:"Choose with intention",detail:"Review your shortlist.",href:"/applications?tab=queued",action:"Review your shortlist",symbol:"◎",completedAt:null},
  {id:"prepare",title:"Practice your next conversation",detail:"Rehearse one interview story.",href:"/applications?tab=pipeline",action:"Open your pipeline",symbol:"◇",completedAt:null},
],milestones:[{id:"first_submission",title:"Out in the world",description:"First dated submission with recorded ATS evidence",symbol:"↗",earnedAt:"2026-09-08T12:00:00Z",seen:false},{id:"first_offer",title:"A new chapter",description:"First dated offer",symbol:"✧",earnedAt:null,seen:false}],records:{confirmedTotal:8,datedConfirmed:8,bestWeekCount:5,bestWeek:"2026-09-07",thisWeekCount:5,bestDayCount:3,bestDays:["2026-09-08"]},history:[]});

test("live progress endpoint exposes evidence-derived records",async({page})=>{
  const result=await page.request.get("/api/backend/application-assistant/progress");
  expect(result.ok()).toBeTruthy();
  const data=await result.json();
  expect(data.quests).toHaveLength(3);
  expect(data.records.confirmedTotal).toBeGreaterThanOrEqual(data.records.datedConfirmed);
  await page.goto("/dashboard");
  await expect(page.getByRole("button",{name:"Edit weekly goal"})).toBeEnabled();
  await expect(page.getByRole("region",{name:"Career progress"})).toBeVisible();
  await page.getByRole("region",{name:"Career progress"}).screenshot({path:"test-results/career-progress-board.png"});
});

test("goals, focus check-ins, player card and milestone collection",async({page})=>{
  const state: any=initial();let writes=0;
  await page.route("**/application-assistant/progress**",async route=>{
    const path=new URL(route.request().url()).pathname;
    if(route.request().method()==="PUT")state.preferences=route.request().postDataJSON();
    if(path.endsWith("/complete")){
      const id=path.split("/").at(-2);const quest=state.quests.find((q:any)=>q.id===id);
      if(!quest.completedAt){quest.completedAt=new Date().toISOString();state.completedCount++;writes++;}
      state.goalReached=state.completedCount>=state.preferences.weeklyGoal;
    }
    if(path.endsWith("/seen"))state.milestones[0].seen=true;
    await route.fulfill({json:state});
  });
  await page.goto("/dashboard");
  await page.getByRole("button",{name:"Edit weekly goal"}).click();
  await page.getByLabel("Weekly actions").selectOption("1");
  await page.getByRole("button",{name:"Save goal",exact:true}).click();
  await page.getByRole("button",{name:"Turn career card to see personal records"}).click();
  await expect(page.getByRole("button",{name:"Show career card front"})).toHaveAttribute("data-flipped","true");
  await page.getByRole("button",{name:/QUEST 01/}).click();
  const dialog=page.getByRole("dialog");
  await expect(dialog.getByRole("heading",{name:"Polish your story"})).toBeVisible();
  await dialog.screenshot({path:"test-results/career-progress-focus.png"});
  await dialog.getByRole("button",{name:"I completed this action ✓"}).click();
  await expect(dialog.getByText(/Your check-in is saved/)).toBeVisible();
  expect(writes).toBe(1);
  await page.keyboard.press("Escape");
  await expect(page.getByText("Weekly goal reached",{exact:true})).toBeVisible();
  await page.getByText("Your milestone collection",{exact:true}).click();
  await expect(page.getByRole("button",{name:"A new chapter, not yet earned"})).toBeDisabled();
  await page.getByRole("button",{name:"Out in the world, earned"}).click();
  await expect(page.getByRole("heading",{name:"Out in the world"})).toBeVisible();
  await page.getByRole("region",{name:"Career progress"}).screenshot({path:"test-results/career-progress-milestones.png"});
  await page.reload();
  await expect(page.getByText("Weekly goal reached",{exact:true})).toBeVisible();
  await page.screenshot({path:"test-results/career-progress-dark.png",fullPage:true});
  const light=page.getByRole("button",{name:"Switch to Light Mode",exact:true});if(await light.isVisible())await light.click();
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:"reduce"});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await expect(page.getByText("Alex Morgan",{exact:true})).toHaveCSS("color","rgb(245, 240, 232)");
  await page.getByRole("region",{name:"Career progress"}).screenshot({path:"test-results/career-progress-mobile.png"});
});

test("a failed check-in never awards progress",async({page})=>{
  await page.route("**/application-assistant/progress**",route=>route.request().method()==="POST" ? route.fulfill({status:500,json:{detail:"Save unavailable"}}) : route.fulfill({json:initial()}));
  await page.goto("/dashboard");await page.getByRole("button",{name:/QUEST 01/}).click();
  const panel=page.getByRole("dialog");await panel.getByRole("button",{name:"I completed this action ✓"}).click();
  await expect(panel.getByRole("alert")).toContainText("Save unavailable");
  await expect(panel.getByRole("button",{name:"I completed this action ✓"})).toBeEnabled();
  await expect(page.getByText("Weekly goal reached",{exact:true})).toHaveCount(0);
});
