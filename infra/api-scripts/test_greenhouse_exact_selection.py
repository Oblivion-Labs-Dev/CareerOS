import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def run_perfect_greenhouse():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="networkidle")

        print("1. Filling basic details...")
        await page.fill("#first_name", "Akshay")
        await page.fill("#last_name", "Borse")
        await page.fill("#email", "amsborse@gmail.com")
        
        # Country phone selector
        try:
            if await page.locator("#country").count() > 0:
                await page.click("#country")
                await asyncio.sleep(0.3)
                us_opt = page.locator('.iti__country:has-text("United States"), [role="option"]:has-text("United States")').first
                if await us_opt.count() > 0:
                    await us_opt.click()
                else:
                    await page.keyboard.press("Escape")
        except Exception as e:
            print("Country select:", e)

        await page.fill("#phone", "425-336-9852")

        # Resume file
        resume_path = str(Path("d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/Akshay_Borse_Resume.pdf").resolve())
        if await page.locator("#resume").count() > 0:
            await page.locator("#resume").set_input_files(resume_path)
            print("Attached resume")
            await asyncio.sleep(0.5)

        # Helper to click combobox and pick matching option
        async def pick_combobox(cb_id, desired_text):
            try:
                cb = page.locator(f"#{cb_id}").first
                if await cb.count() == 0:
                    return
                await cb.click()
                await asyncio.sleep(0.3)
                
                # Check for option items in the opened dropdown
                opt = page.locator(f'[role="option"]:has-text("{desired_text}"), li:has-text("{desired_text}"), .select__option:has-text("{desired_text}")').first
                if await opt.count() > 0 and await opt.is_visible():
                    await opt.click()
                    print(f"Selected [{cb_id}] -> '{desired_text}'")
                else:
                    # Type and press Enter
                    await cb.fill(desired_text)
                    await asyncio.sleep(0.2)
                    await cb.press("Enter")
                    print(f"Typed [{cb_id}] -> '{desired_text}'")
                await asyncio.sleep(0.2)
            except Exception as ex:
                print(f"Error picking [{cb_id}]:", ex)

        # 2. Screening Questions
        await pick_combobox("question_12409841007", "Yes") # Relocation
        await pick_combobox("question_12409842007", "Yes") # Transcripts
        await pick_combobox("question_12409846007", "Yes") # Clearance eligibility
        await pick_combobox("question_12409847007", "None") # Past clearance
        await pick_combobox("question_12409848007", "None") # Export controls
        await pick_combobox("question_12409849007", "Yes") # Work auth
        await pick_combobox("question_12409850007", "Yes") # Sponsorship
        await pick_combobox("question_12409851007", "No") # History
        await pick_combobox("question_12409852007", "No") # Employed by Anduril
        await pick_combobox("question_12409853007", "No") # Conflict of interest
        await pick_combobox("question_12409855007", "LinkedIn") # How heard

        # 3. Demographics
        await pick_combobox("gender", "Male")
        await pick_combobox("hispanic_ethnicity", "No")
        await pick_combobox("veteran_status", "not a protected veteran")
        await pick_combobox("disability_status", "No, I do not have a disability")

        # 4. Text URLs
        if await page.locator("#question_12409845007").count() > 0:
            await page.fill("#question_12409845007", "https://amsborse.github.io/resume")
        if await page.locator("#question_12409854007").count() > 0:
            await page.fill("#question_12409854007", "https://www.linkedin.com/in/amsborse/")

        # Take screenshot of perfect form
        ss_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/application_assistant/screenshots/test_anduril_perfect.png"
        await page.screenshot(path=ss_path, full_page=True)
        print("Perfect form screenshot saved to:", ss_path)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_perfect_greenhouse())
