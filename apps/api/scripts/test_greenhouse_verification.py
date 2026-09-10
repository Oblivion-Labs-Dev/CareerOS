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

        # Fill name & email
        await page.locator('#first_name').fill("Akshay")
        await page.locator('#last_name').fill("Borse")
        await page.locator('#email').fill("amsborse@gmail.com")

        # Fill location with 'Seattle'
        loc = page.locator('#candidate-location')
        await loc.fill("Seattle")
        await asyncio.sleep(1.5)

        opt0 = page.locator('#react-select-candidate-location-option-0')
        if await opt0.count() > 0:
            await opt0.click()
            print("Clicked location opt0")
        await asyncio.sleep(1)

        # Inspect all elements in DOM associated with Location (City)
        loc_elements = await page.evaluate("""() => {
            const res = [];
            const elements = document.querySelectorAll('input:not([type="hidden"]), select, textarea, div.select__control, div[class*="select__control"]');
            elements.forEach(el => {
                const id = el.id || '';
                const name = el.getAttribute('name') || '';
                let label = '';
                if (id) {
                    try {
                        const lbl = document.querySelector(`label[for="${id}"]`);
                        if (lbl && lbl.innerText) label = lbl.innerText.trim();
                    } catch(e) {}
                }
                if (!label) {
                    const parent = el.closest('div.field, div.custom-question, div[class*="question"], div[class*="field"], fieldset');
                    if (parent) {
                        const pLbl = parent.querySelector('label, legend, p.label, span.label, .field__label, [class*="label"]');
                        label = pLbl ? pLbl.innerText.trim() : parent.innerText.split('\\n')[0].trim();
                    }
                }
                if (label.toLowerCase().includes('location') || label.toLowerCase().includes('city')) {
                    res.push({
                        tagName: el.tagName,
                        id: el.id,
                        name: el.name,
                        className: el.className,
                        type: el.type,
                        ariaHidden: el.getAttribute('aria-hidden'),
                        tabIndex: el.tabIndex,
                        value: el.value,
                        innerText: el.innerText,
                        required: el.required,
                        ariaRequired: el.getAttribute('aria-required'),
                        label: label
                    });
                }
            });
            return res;
        }""")
        print("=== LOCATION ELEMENTS FOUND IN DOM ===")
        for el in loc_elements:
            print(" ", el)
        profile = {
            "firstName": "Akshay",
            "lastName": "Borse",
            "email": "amsborse@gmail.com",
            "city": "Seattle",
            "state": "Washington",
            "location": "Seattle, WA",
            "workAuthorization": "Yes",
            "sponsorship": "No",
        }
        res = await verify_browser_dom_state(page, [], profile)
        print("Verification passed:", res.passed)
        print("Issues found:", len(res.issues))
        for iss in res.issues:
            print("  ISSUE:", iss.issue_type, "|", iss.label, "|", iss.details)

        print("\nAll DOM values extracted:")
        for k, v in res.dom_values.items():
            print(f"  '{k}': '{v}'")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
