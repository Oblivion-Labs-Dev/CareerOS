import asyncio
from playwright.async_api import async_playwright

async def inspect_reddit_specific():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/reddit/jobs/8082867", wait_until="networkidle")
        
        frame = page
        for f in page.frames:
            if "greenhouse" in f.url or "job" in f.url:
                frame = f
                break
        
        # Look for demographic wrappers
        sections = await frame.locator('div.field, div.custom-question, div[class*="field"]').all()
        for s in sections:
            txt = (await s.inner_text()).strip()
            if any(k in txt.lower() for k in ["gender identity", "sexual orientation", "ethnicities", "disability"]):
                print("="*60)
                print("TEXT:\n", txt)
                # Find combobox or inputs inside this field
                cbs = await s.locator('input[role="combobox"], div.select__control, div[class*="select__control"], select').all()
                print(f"Controls inside ({len(cbs)}):")
                for c in cbs:
                    tag = await c.evaluate("el => el.tagName")
                    cls = await c.evaluate("el => el.className")
                    cid = await c.evaluate("el => el.id")
                    print(f"  <{tag}> id='{cid}' class='{cls}'")
                    # Try clicking and reading menu
                    try:
                        await c.click(force=True)
                        await asyncio.sleep(0.3)
                        opts = await frame.locator('.select__menu .select__option, div[class*="option"], [role="option"]').all_inner_texts()
                        print(f"  Options visible: {opts}")
                        await page.keyboard.press("Escape")
                    except Exception as e:
                        print(f"  Error: {e}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_reddit_specific())
