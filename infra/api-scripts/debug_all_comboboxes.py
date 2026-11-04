import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

SCREENSHOTS_DIR = Path("d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/application_assistant/screenshots")

async def test_all_comboboxes():
    resume_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/Akshay_Borse_Resume.pdf"
    
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page(viewport={"width": 1280, "height": 900})
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        
        # 1. Basic info
        await page.locator("#first_name").fill("Akshay")
        await page.locator("#last_name").fill("Borse")
        await page.locator("#email").fill("amsborse@gmail.com")
        await page.locator("#phone").fill("425-336-9852")
        
        if os.path.exists(resume_path):
            await page.locator('input[type="file"]').first.set_input_files(resume_path)
            print("Attached resume")
            await asyncio.sleep(0.5)

        # Helper for React Select
        async def solve_react_select(cb_id: str, search_text: str):
            wrapper = page.locator(f'.select__control:has(#{cb_id})').first
            if await wrapper.count() == 0:
                wrapper = page.locator(f'#{cb_id}').first
                if await wrapper.count() == 0:
                    return
            await wrapper.scroll_into_view_if_needed()
            await wrapper.click(force=True)
            await asyncio.sleep(0.2)
            await page.keyboard.type(search_text, delay=30)
            await asyncio.sleep(0.3)
            
            # Click matching option
            opt = page.locator(f'div[id*="-option-"]:has-text("{search_text}"), .select__option:has-text("{search_text}")').first
            if await opt.count() > 0:
                await opt.click(force=True)
            else:
                # Any first option or Enter
                first_opt = page.locator('div[id*="-option-"], .select__option').first
                if await first_opt.count() > 0:
                    await first_opt.click(force=True)
                else:
                    await page.keyboard.press("Enter")
            await asyncio.sleep(0.2)
            print(f"Solved combobox #{cb_id} with '{search_text}'")

        # Get all combobox inputs
        cbs = await page.locator('input[role="combobox"]').all()
        print(f"Found {len(cbs)} comboboxes")
        for cb in cbs:
            cid = await cb.get_attribute("id") or ""
            if not cid or cid == "iti-0__search-input":
                continue
            lbl = ""
            lbl_el = page.locator(f'label[for="{cid}"]').first
            if await lbl_el.count() > 0:
                lbl = (await lbl_el.inner_text()).strip()
            
            lbl_low = lbl.lower()
            if cid == "country" or "country" in lbl_low:
                await solve_react_select(cid, "United States")
            elif "relocate" in lbl_low:
                await solve_react_select(cid, "Yes")
            elif "transcript" in lbl_low:
                await solve_react_select(cid, "No")
            elif "clearance eligibility" in lbl_low:
                await solve_react_select(cid, "Yes")
            elif "clearance level" in lbl_low:
                await solve_react_select(cid, "None")
            elif "export control" in lbl_low:
                await solve_react_select(cid, "U.S. Citizen")
            elif "work authorization" in lbl_low:
                await solve_react_select(cid, "Yes")
            elif "sponsorship" in lbl_low:
                await solve_react_select(cid, "No")
            elif "history with" in lbl_low or "employed by" in lbl_low or "conflict" in lbl_low:
                await solve_react_select(cid, "No")
            elif "how did you hear" in lbl_low:
                await solve_react_select(cid, "LinkedIn")
            elif "gender" in lbl_low:
                await solve_react_select(cid, "Decline")
            elif "hispanic" in lbl_low:
                await solve_react_select(cid, "No")
            elif "veteran" in lbl_low:
                await solve_react_select(cid, "not a protected")
            elif "disability" in lbl_low:
                await solve_react_select(cid, "do not have")
            else:
                await solve_react_select(cid, "No")

        # Text links
        if await page.locator('input[id*="linkedin" i]').count() > 0:
            await page.locator('input[id*="linkedin" i]').first.fill("https://www.linkedin.com/in/amsborse/")
        if await page.locator('input[id*="website" i]').count() > 0:
            await page.locator('input[id*="website" i]').first.fill("https://amsborse.github.io/resume")

        # Pre-submit screenshot
        await page.screenshot(path=str(SCREENSHOTS_DIR / "debug_perfect_all_filled.png"), full_page=True)
        print("Captured debug_perfect_all_filled.png")
        
        await b.close()

if __name__ == "__main__":
    asyncio.run(test_all_comboboxes())
