import asyncio
from playwright.async_api import async_playwright

async def debug_react_select():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        
        # Test selecting Country
        print("Testing #country selection...")
        country_input = page.locator("#country").first
        await country_input.scroll_into_view_if_needed()
        
        # Click the control or input
        parent_control = page.locator('.select__control:has(#country)').first
        if await parent_control.count() > 0:
            await parent_control.click()
        else:
            await country_input.click(force=True)
        await asyncio.sleep(0.3)
        
        # Type 'United States'
        await page.keyboard.type("United States", delay=50)
        await asyncio.sleep(0.5)
        
        # Check visible menu options
        options = await page.locator('.select__menu div, [role="option"], div[id*="-option-"]').all()
        print(f"Found {len(options)} menu options after typing")
        for o in options[:5]:
            txt = await o.inner_text()
            print(f"  Option: '{txt}'")
            
        # Click the first matching option
        us_option = page.locator('div[id*="-option-"]:has-text("United States"), .select__option:has-text("United States")').first
        if await us_option.count() > 0:
            await us_option.click()
            print("Clicked United States option successfully!")
        else:
            await page.keyboard.press("Enter")
            print("Pressed Enter for United States")
            
        await asyncio.sleep(0.5)
        
        # Verify selected value in DOM
        wrapper = page.locator('.select__control:has(#country)').first
        val_text = await wrapper.inner_text()
        print(f"Country selected value: '{val_text.strip()}'")

        # Test selecting Gender
        print("\nTesting #gender selection...")
        gender_input = page.locator("#gender").first
        await gender_input.scroll_into_view_if_needed()
        parent_gender = page.locator('.select__control:has(#gender)').first
        if await parent_gender.count() > 0:
            await parent_gender.click()
        else:
            await gender_input.click(force=True)
        await asyncio.sleep(0.3)
        await page.keyboard.type("Decline", delay=50)
        await asyncio.sleep(0.5)
        
        decline_opt = page.locator('div[id*="-option-"]:has-text("Decline"), .select__option:has-text("Decline")').first
        if await decline_opt.count() > 0:
            await decline_opt.click()
            print("Clicked Decline option for Gender!")
        else:
            await page.keyboard.press("Enter")
            print("Pressed Enter for Gender")
            
        await asyncio.sleep(0.5)
        gender_val = await parent_gender.inner_text()
        print(f"Gender selected value: '{gender_val.strip()}'")
        
        await b.close()

if __name__ == "__main__":
    asyncio.run(debug_react_select())
