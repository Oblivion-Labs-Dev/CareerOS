import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/robinhood/jobs/7899482?t=gh_src=&gh_jid=7899482", wait_until="networkidle", timeout=30000)

        # Inspect all fields
        res = await page.evaluate("""() => {
            const forms = document.querySelectorAll('form');
            const inputs = Array.from(document.querySelectorAll('input[role="combobox"], select, div.select__control'));
            return inputs.map(el => {
                const parent = el.closest('div.field, div.custom-question') || el.parentElement;
                const label = parent ? (parent.querySelector('label, p, span.label') || {}).innerText : '';
                return {
                    id: el.id,
                    tagName: el.tagName,
                    role: el.getAttribute('role'),
                    label: (label || '').slice(0, 100),
                    outer: el.outerHTML.slice(0, 200)
                };
            });
        }""")
        for r in res:
            print("Field:", r)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
