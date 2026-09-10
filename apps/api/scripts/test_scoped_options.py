import asyncio
from playwright.async_api import async_playwright
import re

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/robinhood/jobs/8080244?t=gh_src=&gh_jid=8080244", wait_until="networkidle", timeout=30000)

        cid = "question_68205640"
        el = page.locator(f'#{cid}')
        wrapper = page.locator(f'div.select__control:has([id="{cid}"]), div[class*="control"]:has([id="{cid}"])').first
        target = wrapper if await wrapper.count() > 0 else el

        await target.scroll_into_view_if_needed()
        await target.click(force=True)
        await asyncio.sleep(0.5)

        opt_data = await page.evaluate("""() => {
            var opts = document.querySelectorAll('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option, [role="option"]');
            var res = [];
            for (var i = 0; i < opts.length; i++) {
                if (opts[i].closest('.iti, .iti__country-list')) continue;
                var t = (opts[i].innerText || '').trim();
                if (t && opts[i].offsetParent !== null && t.toLowerCase().indexOf('select...') === -1 && t.toLowerCase().indexOf('choose') === -1) {
                    res.push(t);
                }
            }
            return res;
        }""")
        print("Scoped options count:", len(opt_data))
        print("Scoped options:", opt_data)

        # Click matching option
        target_str = "I have never worked at Robinhood"
        exact_pattern = re.compile(rf"^\s*{re.escape(target_str.strip())}\s*$", re.IGNORECASE)
        opt_to_click = page.locator('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option').filter(has_text=exact_pattern).first
        print("Opt to click count:", await opt_to_click.count())
        if await opt_to_click.count() > 0:
            await opt_to_click.click(force=True)
            await asyncio.sleep(0.5)

        after = await page.evaluate("""(cid) => {
            var el = document.getElementById(cid);
            var wrapper = el ? el.closest('div.select__control, div[class*="select__control"]') : null;
            return {
                inputVal: el ? el.value : null,
                wrapperText: wrapper ? wrapper.innerText : null
            };
        }""", cid)
        print("After click:", after)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
