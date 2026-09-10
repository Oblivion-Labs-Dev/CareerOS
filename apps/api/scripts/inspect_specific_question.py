import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # Test the URL from the job
        await page.goto("https://boards.greenhouse.io/robinhood/jobs/7899482?t=gh_src=&gh_jid=7899482", wait_until="networkidle", timeout=30000)

        # Look specifically for question_68205640
        info = await page.evaluate("""() => {
            const el = document.getElementById('question_68205640') || document.querySelector('[id*="68205640"]');
            if (!el) return 'Element question_68205640 not found on page';
            return {
                id: el.id,
                tagName: el.tagName,
                type: el.type,
                className: el.className,
                role: el.getAttribute('role'),
                outer: el.outerHTML.slice(0, 500)
            };
        }""")
        print("Result for question_68205640 on 7899482:", info)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
