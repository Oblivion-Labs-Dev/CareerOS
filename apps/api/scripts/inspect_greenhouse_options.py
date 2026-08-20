import asyncio
import json
from playwright.async_api import async_playwright

async def inspect_options():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="networkidle")

        comboboxes = await page.locator('input[role="combobox"]').all()
        print(f"Total comboboxes: {len(comboboxes)}")

        for cb in comboboxes:
            cb_id = await cb.get_attribute("id") or ""
            if cb_id in ("iti-0__search-input",):
                continue
            
            # Click combobox to open menu
            try:
                await cb.click()
                await asyncio.sleep(0.2)
                
                # Find all visible options
                options = await page.eval_on_selector_all('[role="option"], .select__option', '''els => els.map(e => e.innerText.trim()).filter(Boolean)''')
                print(f"Combobox [{cb_id}] -> Available Options ({len(options)}): {options[:6]}")
                
                # Press Escape or click body to close
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Error inspecting {cb_id}: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_options())
