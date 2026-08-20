import asyncio
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        page = await b.new_page()
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        
        selects = await page.locator("select").all()
        print(f"Total <select> elements: {len(selects)}")
        for s in selects:
            sid = await s.get_attribute("id")
            sname = await s.get_attribute("name")
            lbl = ""
            if sid:
                l_el = page.locator(f'label[for="{sid}"]').first
                if await l_el.count() > 0:
                    lbl = (await l_el.inner_text()).strip()
            opts = await s.locator("option").all_inner_texts()
            print(f"Select id={sid}, name={sname}, label='{lbl}', options={opts[:5]}")
            
        cbs = await page.locator('input[role="combobox"], [role="combobox"]').all()
        print(f"\nTotal combobox elements: {len(cbs)}")
        for cb in cbs:
            cid = await cb.get_attribute("id")
            cname = await cb.get_attribute("name")
            tag = await cb.evaluate("el => el.tagName")
            lbl = ""
            if cid:
                l_el = page.locator(f'label[for="{cid}"]').first
                if await l_el.count() > 0:
                    lbl = (await l_el.inner_text()).strip()
            print(f"Combobox tag={tag}, id={cid}, name={cname}, label='{lbl}'")
        await b.close()

if __name__ == "__main__":
    asyncio.run(inspect())
