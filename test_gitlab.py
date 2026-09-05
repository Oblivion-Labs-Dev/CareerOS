import asyncio
import os
import sys
from pathlib import Path

repo_root = Path("d:/1 - Projects/Projects/CareerOS/CareerOS")
sys.path.insert(0, str(repo_root / "apps" / "api"))

from dotenv import load_dotenv
load_dotenv(repo_root / "apps" / "api" / ".env")

from playwright.async_api import async_playwright
from app.services.application_assistant.playwright_autopilot_executor import (
    _extract_dom_form_state,
    _fill_standard_and_react_fields,
    get_active_resume_path,
)

async def test():
    print("[1] Launching Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("[2] Navigating to GitLab job...")
        await page.goto("https://job-boards.greenhouse.io/gitlab/jobs/8615319002", timeout=30000)
        await asyncio.sleep(2)
        
        target_frame = page
        for f in page.frames:
            if "greenhouse.io" in f.url and f != page:
                target_frame = f
                print(f"[3] Found frame: {f.url}")
                break
                
        profile = {
            "firstName": "Akshay",
            "lastName": "Borse",
            "email": "amsborse+careeros@gmail.com",
            "phone": "425-336-9852",
            "location": "Auburn, WA",
            "state": "Washington",
            "linkedin": "https://www.linkedin.com/in/amsborse/",
            "github": "https://github.com/amsborse",
            "currentCompany": "Microsoft",
            "currentTitle": "Senior Software Engineer",
        }
        
        print("[4] Calling _fill_standard_and_react_fields...")
        def cb(msg, lvl="info"):
            print(f"   [CB] {msg}")
            
        resume_path = get_active_resume_path(profile)
        print(f"[5] Resume path: {resume_path}")
        
        filled = await _fill_standard_and_react_fields(
            page=target_frame,
            profile=profile,
            answer_lib=[],
            company="GitLab",
            title="Senior Backend Engineer",
            resume_file=resume_path,
            log_cb=cb,
        )
        print(f"[6] Filled: {filled}")
        
        fields, errors = await _extract_dom_form_state(target_frame)
        print(f"[7] DOM Fields count: {len(fields)}, Errors: {errors}")
        await browser.close()
        print("[8] Done!")

if __name__ == "__main__":
    asyncio.run(test())
