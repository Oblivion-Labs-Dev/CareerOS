import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating...")
        await page.goto("https://job-boards.greenhouse.io/extrahopnetworks/jobs/5996341004", wait_until="networkidle", timeout=30000)
        
        # Check location elements
        loc_els = await page.query_selector_all('input[id*="location" i], input[name*="location" i], input[id*="candidate_location" i]')
        print(f"Found {len(loc_els)} location inputs:")
        for el in loc_els:
            el_id = await el.get_attribute("id")
            el_name = await el.get_attribute("name")
            el_type = await el.get_attribute("type")
            el_vis = await el.is_visible()
            val = await el.input_value()
            print(f"  id={el_id}, name={el_name}, type={el_type}, visible={el_vis}, val='{val}'")

        # Let's test typing into the visible one
        for el in loc_els:
            if await el.is_visible():
                # Listen to responses
                page.on("response", lambda res: print("API Response:", res.url, res.status) if "location" in res.url.lower() or "suggest" in res.url.lower() or "geocode" in res.url.lower() else None)

                # Focus, type Seattle, wait 1s, click option 0
                await el.focus()
                await page.keyboard.type("Seattle", delay=100)
                await asyncio.sleep(1.5)

                opt0 = await page.query_selector('#react-select-candidate-location-option-0')
                if opt0:
                    print("Found opt0:", await opt0.inner_text())
                    await opt0.click()
                    await asyncio.sleep(0.5)
                else:
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(0.5)

                # Now check all fields in the form
                all_fields = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('.select, .field, [class*="field"]')).map(f => ({
                        text: f.innerText.replace(/\\n+/g, ' | ').trim(),
                        html: f.outerHTML.slice(0, 300)
                    }));
                }""")
                print(f"Form has {len(all_fields)} fields after location select:")
                for f in all_fields[:10]:
                    print(" -", f["text"])






        await browser.close()

asyncio.run(main())
