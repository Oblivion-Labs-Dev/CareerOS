import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/robinhood/jobs/8080244?t=gh_src=&gh_jid=8080244", wait_until="networkidle", timeout=30000)

        info = await page.evaluate("""() => {
            const el = document.getElementById('question_68205640') || document.querySelector('[id*="68205640"]');
            if (!el) return 'Not found';
            const parent = el.closest('div.field, div.custom-question, div[class*="field"], div[class*="question"]') || el.parentElement;
            return {
                id: el.id,
                tagName: el.tagName,
                className: el.className,
                role: el.getAttribute('role'),
                parentHTML: parent ? parent.outerHTML.slice(0, 800) : null
            };
        }""")
        print("Question info on 8080244:", info)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
