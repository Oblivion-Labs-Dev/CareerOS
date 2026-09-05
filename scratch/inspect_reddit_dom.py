import asyncio
from playwright.async_api import async_playwright

async def inspect_reddit():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/reddit/jobs/8082867", wait_until="networkidle")
        
        # Check iframe or main page
        target = page
        for frame in page.frames:
            if "greenhouse" in frame.url or await frame.locator('form').count() > 0:
                target = frame
                break

        print(f"Target URL: {target.url}")
        
        # Look for the gender/ethnicity/orientation questions
        fields = await target.evaluate("""() => {
            const results = [];
            const allElements = document.querySelectorAll('div.field, div.custom-question, fieldset, div[class*="field"]');
            allElements.forEach(el => {
                const text = el.innerText.trim();
                if (text.includes('gender') || text.includes('sexual') || text.includes('ethnicities') || text.includes('ethnicity')) {
                    const inputs = Array.from(el.querySelectorAll('input, select, textarea, [role="combobox"], div.select__control')).map(inp => ({
                        tag: inp.tagName,
                        type: inp.type,
                        role: inp.getAttribute('role'),
                        id: inp.id,
                        name: inp.getAttribute('name'),
                        className: inp.className,
                        value: inp.value || inp.innerText
                    }));
                    results.push({
                        textSnippet: text.slice(0, 100),
                        inputs: inputs
                    });
                }
            });
            return results;
        }""")
        
        import json
        print(json.dumps(fields, indent=2))
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_reddit())
