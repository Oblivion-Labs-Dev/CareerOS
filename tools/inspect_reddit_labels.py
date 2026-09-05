import asyncio
from playwright.async_api import async_playwright

async def inspect_reddit_labels():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://job-boards.greenhouse.io/reddit/jobs/8082867", wait_until="networkidle")
        
        cbs = await page.locator('input[role="combobox"]').all()
        for idx, cb in enumerate(cbs):
            lbl = await cb.evaluate("""el => {
                var id = el.id;
                // 1. label[for="..."]
                if (id) {
                    try {
                        var l = document.querySelector('label[for="' + id + '"]');
                        if (l && l.innerText && l.innerText.trim()) return "LABEL_FOR: " + l.innerText.trim();
                    } catch(e) {}
                }
                // 2. Climbing parents
                var cur = el.parentElement;
                while (cur && cur.tagName !== 'FORM' && cur.tagName !== 'BODY') {
                    var l = cur.querySelector('label, legend, .label, [class*="label"], p');
                    if (l && l.innerText && l.innerText.trim() && l.innerText.trim().length > 3) {
                        return "PARENT_" + cur.tagName + ": " + l.innerText.trim();
                    }
                    cur = cur.parentElement;
                }
                return "FALLBACK: " + (el.getAttribute('aria-label') || el.id || '');
            }""")
            print(f"CB {idx} id='{await cb.get_attribute('id')}': {lbl}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_reddit_labels())
