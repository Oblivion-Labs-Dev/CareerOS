import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api")
from app.db.store import session_scope, get_kv
from app.services.application_assistant.persistence import list_answer_library
from app.services.application_assistant.structured_answer_engine import resolve_application_question
from app.services.application_assistant.ats_plugin_reference import classify_canonical_key

async def test_fill():
    with session_scope() as db:
        profile = get_kv(db, "profile") or {}
        answer_lib = list_answer_library(db)

    resume_path = str(Path("d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/Akshay_Borse_Resume.pdf").resolve())

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://boards.greenhouse.io/andurilindustries/jobs/5178105007?gh_jid=5178105007", wait_until="networkidle")
        
        print("Page loaded. Starting smart field filler...")

        # 1. Standard text inputs
        if await page.locator("#first_name").count() > 0:
            await page.fill("#first_name", profile.get("firstName", "Akshay"))
            print("Filled first_name")

        if await page.locator("#last_name").count() > 0:
            await page.fill("#last_name", profile.get("lastName", "Borse"))
            print("Filled last_name")

        if await page.locator("#email").count() > 0:
            await page.fill("#email", profile.get("email", "amsborse@gmail.com"))
            print("Filled email")

        if await page.locator("#phone").count() > 0:
            await page.fill("#phone", profile.get("phone", "425-336-9852"))
            print("Filled phone")

        # 2. Resume file
        if await page.locator("#resume").count() > 0 and Path(resume_path).exists():
            await page.locator("#resume").set_input_files(resume_path)
            print("Attached resume file:", resume_path)
            await asyncio.sleep(1.0)

        # 3. Comboboxes & Custom Selects
        comboboxes = await page.locator('input[role="combobox"]').all()
        print(f"Found {len(comboboxes)} comboboxes on page")

        for idx, cb in enumerate(comboboxes):
            cb_id = await cb.get_attribute("id") or ""
            label_text = ""
            if cb_id:
                lbl = page.locator(f'label[for="{cb_id}"]').first
                if await lbl.count() > 0:
                    label_text = (await lbl.inner_text()).strip()

            if not label_text:
                aria = await cb.get_attribute("aria-label") or ""
                label_text = aria or cb_id

            if not label_text or cb_id in ("country", "iti-0__search-input"):
                continue

            canonical_key = classify_canonical_key(f"{label_text} {cb_id}")
            ans_res = await resolve_application_question(
                db=answer_lib,
                question_text=label_text,
                canonical_key=canonical_key or "",
                profile=profile,
                company="Anduril",
                role="Software Engineer",
                resume_text=profile.get("resumeText") or "",
            )
            answer = ans_res.get("answer") or "No"
            print(f"Combobox [{cb_id}] '{label_text}' -> Answer: '{answer}'")

            try:
                # Click to open dropdown
                await cb.click()
                await asyncio.sleep(0.3)
                
                # Type answer to filter options
                await cb.fill(str(answer))
                await asyncio.sleep(0.3)
                
                # Press Enter or click first matching option
                await cb.press("Enter")
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Error selecting combobox {cb_id}: {e}")

        # 4. Other custom text inputs (LinkedIn, Website, etc.)
        other_inputs = await page.locator('input[type="text"]:not([role="combobox"]), input:not([type]):not([role="combobox"])').all()
        for inp in other_inputs:
            inp_id = await inp.get_attribute("id") or ""
            if inp_id in ("first_name", "last_name", "email", "phone"):
                continue
            aria = await inp.get_attribute("aria-label") or ""
            lbl_text = ""
            if inp_id:
                lbl = page.locator(f'label[for="{inp_id}"]').first
                if await lbl.count() > 0:
                    lbl_text = (await lbl.inner_text()).strip()
            label = lbl_text or aria or inp_id

            if "linkedin" in label.lower():
                await inp.fill(profile.get("linkedin", "https://www.linkedin.com/in/amsborse/"))
                print("Filled LinkedIn URL")
            elif "website" in label.lower() or "portfolio" in label.lower():
                await inp.fill(profile.get("portfolio", "https://amsborse.github.io/resume"))
                print("Filled Website URL")

        # Take screenshot of fully filled form
        ss_path = "d:/1 - Projects/Projects/CareerOS/CareerOS/apps/api/data/application_assistant/screenshots/test_anduril_filled.png"
        await page.screenshot(path=ss_path, full_page=True)
        print("Filled screenshot saved to:", ss_path)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_fill())
