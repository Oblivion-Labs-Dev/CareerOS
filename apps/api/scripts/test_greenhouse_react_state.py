import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def run_clean_greenhouse():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="networkidle")

        # 1. Fill basic details
        await page.fill("#first_name", "Akshay")
        await page.fill("#last_name", "Borse")
        await page.fill("#email", "amsborse@gmail.com")
        
        # Select country: click country -> type United States -> click option
        try:
            country_input = page.locator("#country")
            if await country_input.count() > 0:
                await country_input.click()
                await asyncio.sleep(0.3)
                us_opt = page.locator('.iti__country[data-country-code="us"], .iti__country:has-text("United States (+1)")').first
                if await us_opt.count() > 0:
                    await us_opt.click()
                else:
                    await page.keyboard.press("Escape")
        except Exception as e:
            print("Country selection:", e)

        await page.fill("#phone", "425-336-9852")

        # Attach resume
        resume_path = str(Path("d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/Akshay_Borse_Resume.pdf").resolve())
        if await page.locator("#resume").count() > 0:
            await page.locator("#resume").set_input_files(resume_path)
            await asyncio.sleep(0.5)

        # 2. Perfect React Option Clicker
        async def select_react_dropdown(cb_id, match_keywords):
            try:
                cb = page.locator(f"#{cb_id}").first
                if await cb.count() == 0:
                    return False
                
                # Scroll into view and click
                await cb.scroll_into_view_if_needed()
                await cb.click()
                await asyncio.sleep(0.3)

                # Look for listbox options
                options = await page.locator('[role="option"], .select__option, li.select__option').all()
                if not options:
                    # Fallback: type keyword and press Enter
                    await cb.fill(match_keywords[0])
                    await asyncio.sleep(0.2)
                    await cb.press("Enter")
                    return True

                matched_elem = None
                for opt in options:
                    txt = (await opt.inner_text()).strip()
                    for kw in match_keywords:
                        if kw.lower() in txt.lower():
                            matched_elem = opt
                            break
                    if matched_elem:
                        break

                if matched_elem:
                    await matched_elem.click()
                    print(f"Successfully selected [{cb_id}] -> {(await matched_elem.inner_text()).strip()}")
                else:
                    # Click first option if no keyword matches
                    await options[0].click()
                    print(f"Defaulted first option [{cb_id}]")

                await asyncio.sleep(0.2)
                return True
            except Exception as ex:
                print(f"Dropdown error on {cb_id}: {ex}")
                return False

        # Fill all custom questions
        await select_react_dropdown("question_12409841007", ["Yes"]) # Relocation
        await select_react_dropdown("question_12409842007", ["Yes"]) # Transcripts
        await select_react_dropdown("question_12409846007", ["Yes", "eligible"]) # Clearance
        await select_react_dropdown("question_12409847007", ["None", "N/A", "have never held"]) # Past clearance
        await select_react_dropdown("question_12409848007", ["None of the above", "None"]) # Export controls
        await select_react_dropdown("question_12409849007", ["Yes"]) # Work auth
        await select_react_dropdown("question_12409850007", ["Yes"]) # Sponsorship
        await select_react_dropdown("question_12409851007", ["No"]) # History
        await select_react_dropdown("question_12409852007", ["No"]) # Employed by Anduril
        await select_react_dropdown("question_12409853007", ["No"]) # Conflict of interest
        await select_react_dropdown("question_12409855007", ["LinkedIn", "Online Job Board"]) # How heard

        # Demographics
        await select_react_dropdown("gender", ["Male", "Man"])
        await select_react_dropdown("hispanic_ethnicity", ["No"])
        await select_react_dropdown("veteran_status", ["not a protected veteran"])
        await select_react_dropdown("disability_status", ["No, I do not have a disability", "No, I don't have a disability"])

        # Text inputs
        if await page.locator("#question_12409845007").count() > 0:
            await page.fill("#question_12409845007", "https://amsborse.github.io/resume")
        if await page.locator("#question_12409854007").count() > 0:
            await page.fill("#question_12409854007", "https://www.linkedin.com/in/amsborse/")

        # Validate form before screenshot
        ss_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/application_assistant/screenshots/test_anduril_validated.png"
        await page.screenshot(path=ss_path, full_page=True)
        print("Validated form screenshot saved to:", ss_path)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_clean_greenhouse())
