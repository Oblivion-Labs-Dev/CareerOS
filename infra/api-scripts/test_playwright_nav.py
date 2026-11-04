import asyncio
import sys
from playwright.async_api import async_playwright

async def test():
    print("Testing Playwright navigation...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-http2"])
        page = await browser.new_page()
        url = "https://job-boards.greenhouse.io/affirm/jobs/7812982003"
        print("Navigating to:", url)
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            print("Status:", resp.status if resp else "None")
            print("Title:", await page.title())
            form_count = await page.locator("form").count()
            print("Form count:", form_count)
        except Exception as e:
            print("Navigation error:", e)
        finally:
            await browser.close()

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(test())
