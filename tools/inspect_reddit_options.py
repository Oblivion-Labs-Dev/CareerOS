import asyncio
import json
from playwright.async_api import async_playwright

async def inspect_reddit_options():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/reddit/jobs/8082867", wait_until="networkidle")
        
        # Check iframe or main page
        frame = page
        for f in page.frames:
            if "greenhouse" in f.url or "job" in f.url:
                frame = f
                break
                
        # Find all comboboxes / select controls
        combos = await frame.locator('input[role="combobox"], div.select__control, div[class*="select__control"]').all()
        print(f"Found {len(combos)} combobox controls")
        
        for idx, cb in enumerate(combos):
            try:
                lbl = await cb.evaluate("""el => {
                    var p = el.closest('div.field, div.custom-question, div[class*="question"], div[class*="field"], div.form-group, fieldset');
                    if (p) {
                        var l = p.querySelector('label, legend, p.label, span.label');
                        if (l) return l.innerText.trim();
                        return p.innerText.split('\\n')[0].trim();
                    }
                    return el.id || '';
                }""")
                
                await cb.click(force=True)
                await asyncio.sleep(0.3)
                opts = await frame.locator('.select__option, div[class*="option"], [role="option"]').all_inner_texts()
                print(f"\n--- Field {idx}: '{lbl}' ---")
                print(f"Options: {opts[:10]}")
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Error on {idx}: {e}")
                
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_reddit_options())
