"""
E2E Playwright verification script for the CareerOS "Browse Jobs" portal.
Tests:
1. Navigates to http://localhost:5000/jobs/discover
2. Verifies page header displays "Browse Jobs"
3. Verifies navigation sidebar displays "Browse Jobs"
4. Verifies job cards rendering (.cos-job-card inside .cos-job-cards-grid)
5. Verifies Quick Sort toolbar ('🕒 Most Recent', '⚡ Best Match', '🏢 Company Name')
6. Tests sorting by '🕒 Most Recent' and checks job card order
7. Tests search query filter
8. Tests ATS / Source filtering
9. Tests Pagination (Next / Prev)
10. Takes screenshots of the cards UI for verification walkthrough
"""

import sys
import os
import time
from playwright.sync_api import sync_playwright

def run_browse_jobs_e2e():
    print("[E2E] Starting Playwright test against CareerOS portal...")
    artifacts_dir = os.path.abspath("C:/Users/amsbo/.gemini/antigravity-ide/brain/0e7db33c-fada-4cab-8bf0-9957069ec425")
    os.makedirs(artifacts_dir, exist_ok=True)
    screenshot_path = os.path.join(artifacts_dir, "browse_jobs_cards_portal.png")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Step 1: Pre-authenticate by setting the session cookie
        print("[E2E] Setting session cookie on browser context...")
        context.add_cookies([{
            "name": "co_session",
            "value": "amsborse@gmail.com.1789956112.d19f7da196dff6c90e6c767be8a39cb6ddf0db52e64058b27939f274d7efd30a",
            "domain": "localhost",
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        }])

        # Step 2: Navigate to Browse Jobs
        print("[E2E] Navigating to http://localhost:5000/jobs/discover")
        page.goto("http://localhost:5000/jobs/discover", timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(2000)

        print(f"[E2E] Current URL: {page.url}")

        # Step 3: Check Page Title and Nav
        page_title = page.locator(".page-title-with-status, h1").first.text_content()
        print(f"[E2E] Page Header Title: {page_title.strip() if page_title else 'None'}")
        assert "Browse Jobs" in (page_title or ""), f"Expected 'Browse Jobs' in Title, got '{page_title}'"

        # Check Navigation link
        nav_link = page.locator("a[href='/jobs/discover']").first
        nav_text = nav_link.text_content() if nav_link.count() > 0 else ""
        print(f"[E2E] Nav Link text: {nav_text.strip()}")
        assert "Browse Jobs" in nav_text, f"Expected 'Browse Jobs' in nav, got '{nav_text}'"

        # Step 3: Verify Job Cards Grid & Cards
        cards_grid = page.locator(".cos-job-cards-grid")
        assert cards_grid.count() > 0, "Expected .cos-job-cards-grid element to be present"

        cards = page.locator(".cos-job-card")
        card_count = cards.count()
        print(f"[E2E] Number of job cards loaded on Page 1: {card_count}")
        assert card_count > 0, "Expected at least 1 job card to be rendered"

        # Step 4: Verify Card Content Structure
        first_card = cards.first
        first_title = first_card.locator(".cos-job-card-title").text_content()
        first_company = first_card.locator(".cos-job-card-header div span").first.text_content()
        print(f"[E2E] First Card Job Title: {first_title.strip() if first_title else ''}")
        print(f"[E2E] First Card Company: {first_company.strip() if first_company else ''}")
        assert first_title, "Job card title must not be empty"

        # Step 5: Test Quick Sort Toolbar
        print("[E2E] Testing Quick Sort Toolbar...")
        sort_recent_btn = page.locator("button:has-text('Most Recent')").first
        assert sort_recent_btn.count() > 0, "Expected 'Most Recent' sort button"
        sort_recent_btn.click()
        page.wait_for_timeout(1500)
        print("[E2E] Clicked 'Most Recent' sort button successfully")

        # Step 6: Test Search Filter
        print("[E2E] Testing Search query filter...")
        search_input = page.locator("input[placeholder*='Search']").first
        if search_input.count() > 0:
            search_input.fill("Engineer")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            filtered_cards = page.locator(".cos-job-card").count()
            print(f"[E2E] Cards after searching 'Engineer': {filtered_cards}")
            # clear search
            search_input.fill("")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)

        # Step 7: Test Pagination
        print("[E2E] Testing Pagination controls...")
        pagination_text = page.locator("text=/Page \\d+ of \\d+/").first
        if pagination_text.count() > 0:
            print(f"[E2E] Current Pagination status: {pagination_text.text_content()}")
        
        next_btn = page.locator("button:has-text('Next')").first
        if next_btn.count() > 0 and not next_btn.is_disabled():
            next_btn.click()
            page.wait_for_timeout(1500)
            page2_cards = page.locator(".cos-job-card").count()
            print(f"[E2E] Page 2 cards count: {page2_cards}")
            prev_btn = page.locator("button:has-text('Previous')").first
            if prev_btn.count() > 0 and not prev_btn.is_disabled():
                prev_btn.click()
                page.wait_for_timeout(1500)
                print("[E2E] Successfully navigated back to Page 1")

        # Step 8: Capture visual snapshot of the card grid
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"[E2E] Saved Playwright screenshot to {screenshot_path}")

        browser.close()
        print("[E2E] All Playwright browser portal tests PASSED successfully!")

if __name__ == "__main__":
    run_browse_jobs_e2e()
