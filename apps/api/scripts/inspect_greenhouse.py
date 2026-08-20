import asyncio
import json
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="networkidle")
        
        js_code = """
        () => {
            const results = [];
            const fields = document.querySelectorAll('input, textarea, select, [role="combobox"]');
            fields.forEach((el, i) => {
                let label = '';
                if (el.id) {
                    const l = document.querySelector('label[for="' + el.id + '"]');
                    if (l) label = l.innerText;
                }
                if (!label) {
                    const closestField = el.closest('.field, [data-qa], .form-group, div');
                    if (closestField) {
                        const l = closestField.querySelector('label, .label, .field__label');
                        if (l) label = l.innerText;
                    }
                }
                results.push({
                    idx: i,
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    role: el.getAttribute('role') || '',
                    label: label.trim().substring(0, 80)
                });
            });
            return results;
        }
        """
        inputs = await page.evaluate(js_code)
        for item in inputs:
            print(json.dumps(item))
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
