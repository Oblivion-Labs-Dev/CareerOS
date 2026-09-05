import asyncio
from playwright.async_api import async_playwright

async def inspect_reddit_options_all():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/reddit/jobs/8082867", wait_until="networkidle")
        
        cbs = await page.locator('input[role="combobox"]').all()
        for idx, cb in enumerate(cbs):
            cid = await cb.get_attribute("id")
            if cid == "iti-0__search-input":
                continue
            
            # Label
            lbl = await cb.evaluate("""el => {
                var id = el.id;
                if (id) {
                    try {
                        var l = document.querySelector('label[for="' + id + '"]');
                        if (l && l.innerText && l.innerText.trim()) return l.innerText.trim();
                    } catch(e) {}
                }
                return el.id || '';
            }""")
            
            # Click container to open menu
            wrapper = page.locator(f'div.select__control:has([id="{cid}"]), div[class*="control"]:has([id="{cid}"])').first
            target = wrapper if await wrapper.count() > 0 else cb
            await target.click(force=True)
            await asyncio.sleep(0.3)
            
            opts = await page.locator('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option').all_inner_texts()
            print(f"\nQ: [{cid}] '{lbl}'")
            print(f"Options ({len(opts)}): {opts}")
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.1)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_reddit_options_all())
