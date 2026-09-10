import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/robinhood/jobs/7899482?t=gh_src=&gh_jid=7899482", wait_until="networkidle", timeout=30000)

        # Inspect question_68205640 or all custom questions
        res = await page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('[id*="question"], div.field, div.custom-question'));
            return els.map(el => ({
                id: el.id,
                tagName: el.tagName,
                className: el.className,
                role: el.getAttribute('role'),
                outerHTML: el.outerHTML.slice(0, 300)
            })).filter(x => x.id && (x.id.includes('68205640') || x.id.includes('question')));
        }""")
        print("Found matching elements:", len(res))
        for r in res[:10]:
            print("  *", r)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
