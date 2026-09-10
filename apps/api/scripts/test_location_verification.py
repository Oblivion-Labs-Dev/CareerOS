import asyncio
from playwright.async_api import async_playwright
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.application_assistant.browser_verifier import verify_browser_dom_state

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/extrahopnetworks/jobs/5996341004", wait_until="networkidle", timeout=30000)

        loc = page.locator('#candidate-location')
        await loc.focus()
        await loc.press_sequentially("Seattle", delay=50)
        await asyncio.sleep(1.5)

        opt_locator = page.locator('[id*="candidate-location-option"]').first
        if await opt_locator.count() > 0:
            print("Clicking option:", await opt_locator.inner_text())
            await opt_locator.click()
            await asyncio.sleep(0.5)

        # Run verify_browser_dom_state
        profile = {
            "firstName": "Akshay",
            "lastName": "Borse",
            "email": "amsborse@gmail.com",
            "phone": "+1 206-555-0199",
            "city": "Seattle",
            "state": "Washington",
            "location": "Seattle, WA",
            "workAuth": {"authorizedToWorkInUS": True, "requiresSponsorshipNowOrFuture": False}
        }
        res = await verify_browser_dom_state(page, [], profile)
        print("Verification passed?:", res.passed)
        print("DOM values for location:")
        for k, v in res.dom_values.items():
            if "location" in k.lower() or "city" in k.lower():
                print(f"  {k} = {v}")
        print("Any location/city issues?:")
        for iss in res.issues:
            if "location" in iss.label.lower() or "city" in iss.label.lower():
                print("  *", iss)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
