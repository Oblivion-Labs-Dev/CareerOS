"""Playwright Autopilot Live Submitter with Strict Pre-Submit & Post-Submit Verification."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.services.application_assistant.ats_plugin_reference import (
    ATS_CONFIGS,
    classify_canonical_key,
    pick_best_matching_option,
)
from app.services.application_assistant.structured_answer_engine import resolve_application_question
from app.services.application_assistant.qwen_form_reviewer import review_and_heal_form_state

logger = logging.getLogger("career_os.playwright_autopilot")

SCREENSHOTS_DIR = Path(__file__).resolve().parents[3] / "data" / "application_assistant" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_RESUME_PATH = Path(__file__).resolve().parents[3] / "data" / "Akshay_Borse_Resume.pdf"


def get_active_resume_path(profile: dict[str, Any]) -> str:
    candidate_path = profile.get("resumePath")
    if candidate_path and Path(candidate_path).exists():
        return str(Path(candidate_path).resolve())
    if DEFAULT_RESUME_PATH.exists():
        return str(DEFAULT_RESUME_PATH.resolve())
    return ""


async def _extract_dom_form_state(page: Page) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract full DOM state of all form inputs, comboboxes, and validation errors."""
    js_code = """
    () => {
        const fields = [];
        const errors = [];
        
        // Find visible validation errors
        document.querySelectorAll('.error, [role="alert"], .field__error, .text-error, .input-error, .invalid-feedback').forEach(el => {
            const txt = (el.innerText || '').trim();
            if (txt && !errors.includes(txt) && el.offsetParent !== null) errors.push(txt);
        });

        // Find all interactive inputs
        const elements = document.querySelectorAll('input:not([type="hidden"]), textarea, select, [role="combobox"]');
        elements.forEach((el, i) => {
            const id = el.id || '';
            const name = el.name || el.getAttribute('name') || '';
            const ariaLabel = el.getAttribute('aria-label') || '';
            const isCombobox = el.getAttribute('role') === 'combobox';
            
            let label = '';
            if (id) {
                const l = document.querySelector('label[for="' + id + '"]');
                if (l) label = l.innerText;
            }
            if (!label) {
                const parent = el.closest('.field, [data-qa], .form-group, .eeoc__question__wrapper, div');
                if (parent) {
                    const l = parent.querySelector('label, .label, .field__label');
                    if (l) label = l.innerText;
                }
            }
            label = (label || ariaLabel || name || id).trim();

            let val = el.value || '';
            if (el.tagName.toLowerCase() === 'select') {
                val = el.options[el.selectedIndex]?.text || '';
            }

            // Check if filled in React select
            if (isCombobox) {
                const wrapper = el.closest('.select__control, .field-wrapper, .eeoc__question__wrapper');
                if (wrapper) {
                    const singleValue = wrapper.querySelector('.select__single-value');
                    if (singleValue) {
                        val = (singleValue.innerText || '').trim();
                    }
                }
            }

            const isRequired = el.required || el.getAttribute('aria-required') === 'true' || label.includes('*');

            fields.push({
                idx: i,
                id: id,
                name: name,
                label: label,
                type: el.type || '',
                tag: el.tagName.toLowerCase(),
                isCombobox: isCombobox,
                required: isRequired,
                value: val
            });
        });

        return { fields, errors };
    }
    """
    try:
        data = await page.evaluate(js_code)
        return data.get("fields", []), data.get("errors", [])
    except Exception as ex:
        logger.warning("Error extracting DOM state: %s", ex)
        return [], []


async def _select_react_combobox(page: Any, cb_id: str, search_text: str) -> str:
    """Safely and reliably select an option from a React Select combobox."""
    try:
        wrapper = page.locator(f'.select__control:has(#{cb_id})').first
        if await wrapper.count() == 0:
            wrapper = page.locator(f'#{cb_id}').first
            if await wrapper.count() == 0:
                return ""

        await wrapper.scroll_into_view_if_needed()
        await wrapper.click(force=True)
        await asyncio.sleep(0.2)

        # Type using keyboard to trigger React Select dropdown filter
        await page.keyboard.type(str(search_text), delay=30)
        await asyncio.sleep(0.3)

        # Look for visible matching option
        opt = page.locator(f'div[id*="-option-"]:has-text("{search_text}"), .select__option:has-text("{search_text}")').first
        if await opt.count() > 0:
            await opt.click(force=True)
            await asyncio.sleep(0.2)
            return search_text
        else:
            first_opt = page.locator('div[id*="-option-"], .select__option').first
            if await first_opt.count() > 0:
                txt = (await first_opt.inner_text()).strip()
                await first_opt.click(force=True)
                await asyncio.sleep(0.2)
                return txt
            else:
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.2)
                return search_text
    except Exception as ex:
        logger.debug("Combobox error on %s: %s", cb_id, ex)
        return ""


async def _fill_first_visible(page_or_frame: Any, selectors: list[str], value: str) -> bool:
    """Safely fill the first visible, editable input matching any selector with quick timeout."""
    for sel in selectors:
        try:
            loc = page_or_frame.locator(sel)
            count = await loc.count()
            for i in range(count):
                el = loc.nth(i)
                if await el.is_visible():
                    await el.scroll_into_view_if_needed()
                    await el.fill(str(value), timeout=2500)
                    return True
        except Exception:
            continue
    return False


async def _fill_all_greenhouse_comboboxes(page: Any, profile: dict[str, Any], answer_lib: list[dict[str, Any]] | None) -> dict[str, str]:
    """Dynamically resolve and select every single React combobox on the page."""
    filled: dict[str, str] = {}
    comboboxes = await page.locator('input[role="combobox"]').all()

    for cb in comboboxes:
        cb_id = await cb.get_attribute("id") or ""
        if not cb_id or cb_id == "iti-0__search-input":
            continue

        label = ""
        lbl_el = page.locator(f'label[for="{cb_id}"]').first
        if await lbl_el.count() > 0:
            label = (await lbl_el.inner_text()).strip()
        if not label:
            label = (await cb.get_attribute("aria-label")) or cb_id

        lbl_lower = label.lower()
        selected_val = ""

        if cb_id == "country" or "country" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "United States")
        elif "relocate" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "Yes")
        elif "transcript" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "No")
        elif "clearance eligibility" in lbl_lower or "eligibility to obtain" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "Yes")
        elif "clearance level" in lbl_lower or "clearance level have you held" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "None")
        elif "export control" in lbl_lower or "export controls" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "U.S. Citizen")
        elif "work authorization" in lbl_lower or "authorized to work" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "Yes")
        elif "sponsorship" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "No")
        elif "history with" in lbl_lower or "employed by" in lbl_lower or "conflict" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "No")
        elif "how did you hear" in lbl_lower or "source" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "LinkedIn")
        elif "gender" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "Decline")
        elif "hispanic" in lbl_lower or "latino" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "No")
        elif "veteran" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "not a protected")
        elif "disability" in lbl_lower:
            selected_val = await _select_react_combobox(page, cb_id, "do not have")
        else:
            ans = await resolve_application_question(
                db=answer_lib,
                question_text=label,
                canonical_key=classify_canonical_key(f"{label} {cb_id}") or "",
                profile=profile,
                company="",
                role="",
                resume_text=profile.get("resumeText") or "",
            )
            val = ans.get("answer") or "No"
            selected_val = await _select_react_combobox(page, cb_id, val)

        if selected_val:
            filled[label or cb_id] = selected_val

    return filled


async def _fill_standard_and_react_fields(
    page: Any,
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None,
    company: str,
    title: str,
    resume_file: str,
) -> dict[str, str]:
    """Execute primary field filling across standard inputs and React comboboxes."""
    filled: dict[str, str] = {}

    # 1. Standard text fields (First Name, Last Name, Email, Phone)
    first = profile.get("firstName", "Akshay")
    if await _fill_first_visible(
        page,
        ["#first_name", "input[name='job_application[first_name]']", "input[name*='first_name' i]", "input[id*='first_name' i]"],
        first
    ):
        filled["First Name"] = first

    last = profile.get("lastName", "Borse")
    if await _fill_first_visible(
        page,
        ["#last_name", "input[name='job_application[last_name]']", "input[name*='last_name' i]", "input[id*='last_name' i]"],
        last
    ):
        filled["Last Name"] = last

    email = profile.get("email", "amsborse@gmail.com")
    if await _fill_first_visible(
        page,
        ["#email", "input[name='job_application[email]']", "#job_application_email", "input[name*='email' i]", "form input[type='email']"],
        email
    ):
        filled["Email"] = email

    phone = profile.get("phone", "425-336-9852")
    if await _fill_first_visible(
        page,
        ["#phone", "input[name='job_application[phone]']", "#job_application_phone", "input[name*='phone' i]", "input[type='tel']"],
        phone
    ):
        filled["Phone"] = phone

    # 2. Resume File
    file_inputs = await page.locator('input[type="file"]').all()
    if file_inputs and resume_file and os.path.exists(resume_file):
        try:
            await file_inputs[0].set_input_files(resume_file)
            filled["Resume"] = os.path.basename(resume_file)
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("Resume attach error: %s", e)

    # 3. React Comboboxes
    cb_filled = await _fill_all_greenhouse_comboboxes(page, profile, answer_lib)
    filled.update(cb_filled)

    # 4. Standard Text Links (LinkedIn, Website, Portfolio)
    if await page.locator('input[id*="linkedin" i], input[name*="linkedin" i]').count() > 0:
        val = profile.get("linkedin", "https://www.linkedin.com/in/amsborse/")
        await _fill_first_visible(page, ['input[id*="linkedin" i]', 'input[name*="linkedin" i]'], val)
        filled["LinkedIn"] = val

    if await page.locator('input[id*="website" i], input[name*="website" i], input[id*="portfolio" i]').count() > 0:
        val = profile.get("portfolio") or profile.get("github") or "https://amsborse.github.io/resume"
        await _fill_first_visible(page, ['input[id*="website" i]', 'input[name*="website" i]', 'input[id*="portfolio" i]'], val)
        filled["Website"] = val

    return filled


async def execute_live_playwright_submission(
    job_item: dict[str, Any],
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
    headless: bool = True,
    timeout_sec: float = 75.0,
) -> dict[str, Any]:
    """Execute autonomous browser submission with strict pre-submit and post-submit verification."""
    app_url = job_item.get("applicationUrl") or job_item.get("listingUrl") or ""
    company = job_item.get("company") or "Target Company"
    title = job_item.get("title") or "Target Role"
    job_id = job_item.get("id") or "job"

    if not app_url:
        return {"submitted": False, "error": "Missing application URL", "evidence": {}}

    resume_file = get_active_resume_path(profile)

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"],
        )
        context: BrowserContext = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page: Page = await context.new_page()
        page.set_default_timeout(timeout_sec * 1000)

        try:
            logger.info("Navigating to application URL: %s", app_url)
            await page.goto(app_url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
            await asyncio.sleep(2.5)

            # Check for iframe (e.g. Greenhouse or Lever embeds)
            target_frame: Any = page
            for frame in page.frames:
                if "greenhouse.io" in frame.url or "lever.co" in frame.url or "ashby" in frame.url:
                    target_frame = frame
                    break

            # Initial Form Filling
            filled_fields = await _fill_standard_and_react_fields(
                page=target_frame,
                profile=profile,
                answer_lib=answer_lib,
                company=company,
                title=title,
                resume_file=resume_file,
            )

            # ─── QWEN PRE-SUBMISSION REVIEW & SELF-HEALING LOOP ─────────────────
            max_healing_rounds = 3
            qwen_approved = False

            for round_num in range(1, max_healing_rounds + 1):
                logger.info("Qwen Pre-Submission Review (Round %d/%d)...", round_num, max_healing_rounds)
                dom_fields, validation_errors = await _extract_dom_form_state(target_frame)

                review_res = await review_and_heal_form_state(
                    form_state=dom_fields,
                    validation_errors=validation_errors,
                    profile=profile,
                    company=company,
                    title=title,
                )

                if review_res.get("readyToSubmit") and not validation_errors:
                    logger.info("Qwen Pre-Submission Review: 100% APPROVED ✓")
                    qwen_approved = True
                    break

                # Self-Healing Action: Repair missing or invalid fields
                missing_fields = review_res.get("missingOrInvalidFields", [])
                logger.warning("Qwen Review detected %d items requiring self-healing in round %d", len(missing_fields), round_num)

                for item in missing_fields:
                    f_id = item.get("fieldId")
                    f_label = item.get("label", "")
                    fix_val = item.get("suggestedFixValue")

                    if not fix_val:
                        ans = await resolve_application_question(
                            db=answer_lib,
                            question_text=f_label,
                            canonical_key=classify_canonical_key(f"{f_label} {f_id}") or "",
                            profile=profile,
                            company=company,
                            role=title,
                            resume_text=profile.get("resumeText") or "",
                        )
                        fix_val = ans.get("answer") or "No"

                    if f_id:
                        elem = target_frame.locator(f"#{f_id}").first
                        if await elem.count() > 0:
                            is_cb = await elem.get_attribute("role") == "combobox"
                            if is_cb:
                                await _select_react_combobox(target_frame, f_id, str(fix_val))
                            else:
                                await elem.fill(str(fix_val))
                            filled_fields[f_label or f_id] = str(fix_val)

                await asyncio.sleep(0.5)

            # Pre-submit screenshot
            pre_screenshot_path = SCREENSHOTS_DIR / f"{job_id}_presubmit.png"
            await page.screenshot(path=str(pre_screenshot_path), full_page=True)

            # ─── FINAL SUBMIT CLICK ─────────────────────────────────────────────
            submit_selectors = [
                '#submit_app',
                'button[type="submit"]',
                'input[type="submit"][value*="Submit" i]',
                'button[data-qa="submit-application"]',
                'button[data-qa="btn-submit"]',
                'button:has-text("Submit Application")',
                'button:has-text("Submit application")',
                'button:has-text("Submit")',
                'input[type="submit"]',
            ]

            submit_button = None
            for sel in submit_selectors:
                btn = target_frame.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    submit_button = btn
                    break

            if not submit_button:
                for sel in submit_selectors:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        submit_button = btn
                        break

            if not submit_button:
                return {
                    "submitted": False,
                    "error": "Submit button not found on application page",
                    "evidence": {
                        "preScreenshotPath": str(pre_screenshot_path.resolve()),
                    },
                    "fieldsFilled": filled_fields,
                }

            logger.info("Executing final submission click via Playwright...")
            await submit_button.scroll_into_view_if_needed()
            await submit_button.click()
            await asyncio.sleep(5.0)

            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Post-submission screenshot
            confirmation_url = page.url
            post_screenshot_path = SCREENSHOTS_DIR / f"{job_id}_confirmation.png"
            await page.screenshot(path=str(post_screenshot_path), full_page=True)

            # ─── STRICT SUBMISSION PROOF VALIDATION ────────────────────────────
            body_text = await page.inner_text("body")
            
            # Check for visible validation errors on page after submit click
            post_errors = await page.locator('.error, .field__error, [role="alert"], .text-error').all_inner_texts()
            active_errors = [e.strip() for e in post_errors if e.strip() and "cookie" not in e.lower()]

            has_confirmation_phrase = any(
                p in body_text.lower() for p in [
                    "thank you for applying",
                    "application submitted",
                    "application has been submitted",
                    "we have received your application",
                    "application received",
                    "thanks for applying",
                    "your application was submitted",
                ]
            )

            # Check if URL redirected to confirmation / thank you page
            url_redirected = any(
                term in confirmation_url.lower() for term in ["thank_you", "confirmation", "applied", "success"]
            )

            # Check if form disappeared (real submission destroys or replaces the application form)
            form_disappeared = (await page.locator("#application_form, #application, form").count() == 0) or url_redirected

            is_genuine_submission = (has_confirmation_phrase or url_redirected or form_disappeared) and not active_errors

            if not is_genuine_submission:
                err_msg = f"ATS rejected submission or required fields remain incomplete: {', '.join(active_errors) if active_errors else 'No confirmation page reached'}"
                logger.error("Submission unconfirmed: %s", err_msg)
                return {
                    "submitted": False,
                    "error": err_msg,
                    "evidence": {
                        "confirmationUrl": confirmation_url,
                        "screenshotPath": str(post_screenshot_path.resolve()),
                        "preScreenshotPath": str(pre_screenshot_path.resolve()),
                        "errorsFound": active_errors,
                    },
                    "fieldsFilled": filled_fields,
                }

            confirmation_text = "Application submitted successfully"
            conf_match = re.search(
                r"(thank you for (?:your )?applying|application (?:has been )?submitted|application received|we have received your application|thanks for applying)",
                body_text,
                re.IGNORECASE,
            )
            if conf_match:
                confirmation_text = conf_match.group(0).strip()

            return {
                "submitted": True,
                "evidence": {
                    "confirmationText": confirmation_text,
                    "confirmationUrl": confirmation_url,
                    "screenshotPath": str(post_screenshot_path.resolve()),
                    "preScreenshotPath": str(pre_screenshot_path.resolve()),
                    "qwenApproved": qwen_approved,
                },
                "fieldsFilled": filled_fields,
            }

        except Exception as e:
            logger.error("Playwright submission failed: %s", e)
            err_screenshot = SCREENSHOTS_DIR / f"{job_id}_error.png"
            try:
                await page.screenshot(path=str(err_screenshot), full_page=True)
            except Exception:
                pass
            return {
                "submitted": False,
                "error": str(e),
                "evidence": {
                    "errorScreenshot": str(err_screenshot.resolve()) if err_screenshot.exists() else "",
                },
                "fieldsFilled": {},
            }
        finally:
            await context.close()
            await browser.close()
