import asyncio
from playwright.async_api import async_playwright

async def inspect_reddit():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/reddit/jobs/8082867", wait_until="networkidle")
        
        # Check all frames
        for f in page.frames:
            body = await f.inner_text("body")
            if "gender" in body.lower():
                print("Found frame:", f.url)
                # find all labels
                labels = await f.locator("label, legend, p").all_inner_texts()
                for l in labels:
                    if any(k in l.lower() for k in ["gender", "sexual", "ethnicities", "disability"]):
                        print("LABEL:", l)
                
                # find all combobox inputs
                cbs = await f.locator('input[role="combobox"]').all()
                print(f"Total role=combobox inputs: {len(cbs)}")
                for i, cb in enumerate(cbs):
                    cid = await cb.get_attribute("id")
                    aria = await cb.get_attribute("aria-label")
                    print(f"CB {i}: id='{cid}' aria='{aria}'")
                    try:
                        # scroll and click
                        await cb.click(force=True)
                        await asyncio.sleep(0.2)
                        opts = await f.locator('[role="option"], .select__option').all_inner_texts()
                        print(f"  Options ({len(opts)}): {opts[:6]}")
                        await f.keyboard.press("Escape")
                    except Exception as e:
                        print(f"  Err: {e}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_reddit())
