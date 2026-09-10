import asyncio
from playwright.async_api import async_playwright
import sys
from pathlib import Path

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/extrahopnetworks/jobs/5996341004", wait_until="networkidle", timeout=30000)

        loc = page.locator('#candidate-location')
        await loc.focus()
        await loc.press_sequentially("Seattle", delay=50)
        await asyncio.sleep(2.0)

        # Inspect what elements appeared on page
        elements = await page.evaluate("""() => {
            const listbox = document.querySelector('[id*="candidate-location"]');
            const options = Array.from(document.querySelectorAll('[id*="candidate-location-option"], div[class*="select__menu"] div[class*="option"], div[class*="select__option"], .pac-item'));
            return {
                listboxOuter: listbox ? listbox.outerHTML.slice(0, 300) : null,
                optionCount: options.length,
                options: options.map(o => ({
                    id: o.id,
                    className: o.className,
                    text: o.innerText,
                    visible: !!(o.offsetWidth || o.offsetHeight || o.getClientRects().length)
                }))
            };
        }""")
        print("Dropdown evaluation after press_sequentially:", elements)

        # If options found, click the first one matching Seattle
        opt_locator = page.locator('[id*="candidate-location-option"], div[class*="select__menu"] div[class*="option"], div[class*="select__option"]').first
        if await opt_locator.count() > 0:
            print("Clicking option...")
            await opt_locator.click()
            await asyncio.sleep(1.0)
            
            # Check what DOM looks like now
            after_click = await page.evaluate("""() => {
                const el = document.querySelector('#candidate-location');
                const wrapper = el ? el.closest('div.select__control, div[class*="select__control"]') : null;
                const valueContainer = wrapper ? wrapper.querySelector('[class*="ValueContainer"], [class*="singleValue"]') : null;
                return {
                    inputVal: el ? el.value : null,
                    wrapperText: wrapper ? wrapper.innerText : null,
                    valueContainerText: valueContainer ? valueContainer.innerText : null,
                    wrapperOuter: wrapper ? wrapper.outerHTML.slice(0, 400) : null
                };
            }""")
            print("After click:", after_click)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
