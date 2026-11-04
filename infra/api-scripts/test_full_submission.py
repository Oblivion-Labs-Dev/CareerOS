import asyncio
import json
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright

SCREENSHOTS_DIR = Path("d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/application_assistant/screenshots")

async def test_full_submission():
    resume_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/Akshay_Borse_Resume.pdf"
    
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        context = await b.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()
        
        print("Navigating to Anduril...")
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="domcontentloaded")
        await asyncio.sleep(2.5)
        
        # 1. Fill basic text fields
        await page.locator("#first_name").fill("Akshay")
        await page.locator("#last_name").fill("Borse")
        await page.locator("#email").fill("amsborse@gmail.com")
        await page.locator("#phone").fill("425-336-9852")
        
        # 2. Upload resume
        file_input = page.locator('input[type="file"]').first
        if await file_input.count() > 0 and os.path.exists(resume_path):
            await file_input.set_input_files(resume_path)
            print("Attached resume PDF")
            await asyncio.sleep(0.5)
            
        # Helper for React select combobox
        async def fill_cb(cb_id: str, search_text: str):
            cb = page.locator(f"#{cb_id}").first
            if await cb.count() == 0:
                return False
            await cb.scroll_into_view_if_needed()
            await cb.click(force=True)
            await asyncio.sleep(0.2)
            await cb.fill(search_text)
            await asyncio.sleep(0.2)
            
            # Select matching menu option
            opts = await page.locator('.select__menu .select__option, [role="option"]').all()
            for opt in opts:
                if await opt.is_visible():
                    txt = (await opt.inner_text()).strip()
                    if search_text.lower() in txt.lower():
                        await opt.click(force=True)
                        await asyncio.sleep(0.2)
                        print(f"Selected '{txt}' for #{cb_id}")
                        return True
            await cb.press("Enter")
            await asyncio.sleep(0.2)
            print(f"Pressed Enter '{search_text}' for #{cb_id}")
            return True

        # 3. Fill all comboboxes
        cbs = await page.locator('input[role="combobox"]').all()
        for cb in cbs:
            cb_id = await cb.get_attribute("id") or ""
            if not cb_id or cb_id == "iti-0__search-input":
                continue
                
            label = ""
            lbl_el = page.locator(f'label[for="{cb_id}"]').first
            if await lbl_el.count() > 0:
                label = (await lbl_el.inner_text()).strip()
                
            print(f"Processing combobox [{cb_id}] '{label}'...")
            
            lbl_lower = label.lower()
            if cb_id == "country" or "country" in lbl_lower:
                await fill_cb(cb_id, "United States")
            elif "relocate" in lbl_lower:
                await fill_cb(cb_id, "Yes")
            elif "transcript" in lbl_lower:
                await fill_cb(cb_id, "No")
            elif "clearance eligibility" in lbl_lower:
                await fill_cb(cb_id, "Yes")
            elif "clearance level have you held" in lbl_lower:
                await fill_cb(cb_id, "None")
            elif "export control" in lbl_lower:
                await fill_cb(cb_id, "U.S. Citizen")
            elif "work authorization" in lbl_lower:
                await fill_cb(cb_id, "Yes")
            elif "sponsorship" in lbl_lower:
                await fill_cb(cb_id, "No")
            elif "history with anduril" in lbl_lower or "employed by anduril" in lbl_lower or "conflict" in lbl_lower:
                await fill_cb(cb_id, "No")
            elif "how did you hear" in lbl_lower:
                await fill_cb(cb_id, "LinkedIn")
            elif "gender" in lbl_lower:
                await fill_cb(cb_id, "Decline")
            elif "hispanic" in lbl_lower:
                await fill_cb(cb_id, "No")
            elif "veteran" in lbl_lower:
                await fill_cb(cb_id, "not a protected")
            elif "disability" in lbl_lower:
                await fill_cb(cb_id, "do not have")
            else:
                await fill_cb(cb_id, "No")

        # 4. Fill text links
        if await page.locator('input[id*="linkedin" i], input[name*="linkedin" i]').count() > 0:
            await page.locator('input[id*="linkedin" i], input[name*="linkedin" i]').first.fill("https://www.linkedin.com/in/amsborse/")
        if await page.locator('input[id*="website" i], input[name*="website" i]').count() > 0:
            await page.locator('input[id*="website" i], input[name*="website" i]').first.fill("https://amsborse.github.io/resume")

        # Take filled screenshot
        await page.screenshot(path=str(SCREENSHOTS_DIR / "test_perfect_filled.png"), full_page=True)
        print("Captured test_perfect_filled.png")
        
        # Check validation errors before clicking submit
        errs = await page.locator('.error, .field__error, [role="alert"]').all_inner_texts()
        visible_errs = [e.strip() for e in errs if e.strip()]
        print(f"Validation errors before submit: {visible_errs}")
        
        # Click submit
        submit_btn = page.locator('#submit_app, button[type="submit"]:has-text("Submit")').first
        if await submit_btn.count() > 0:
            print("Clicking Submit button...")
            await submit_btn.click()
            await asyncio.sleep(5.0)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

        await page.screenshot(path=str(SCREENSHOTS_DIR / "test_perfect_after_submit.png"), full_page=True)
        print("Final URL:", page.url)
        
        body_text = await page.inner_text("body")
        has_confirmation = any(p in body_text.lower() for p in ["thank you for applying", "application submitted", "received your application", "thanks for applying"])
        print("Has confirmation text:", has_confirmation)
        
        remaining_errs = await page.locator('.error, .field__error, [role="alert"]').all_inner_texts()
        print("Remaining validation errors:", [e.strip() for e in remaining_errs if e.strip()])
        
        await b.close()

if __name__ == "__main__":
    asyncio.run(test_full_submission())
