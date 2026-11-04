import asyncio
import sys
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        url = "https://job-boards.greenhouse.io/affirm/jobs/7812982003"
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        
        inputs = await page.locator("input, select, textarea").all()
        print(f"Total form controls on Affirm: {len(inputs)}")
        for inp in inputs:
            itype = await inp.get_attribute("type") or await inp.evaluate("el => el.tagName")
            iid = await inp.get_attribute("id") or ""
            iname = await inp.get_attribute("name") or ""
            aria = await inp.get_attribute("aria-label") or ""
            print(f"Control: type={itype}, id={iid}, name={iname}, aria='{aria}'")
        await b.close()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(inspect())
