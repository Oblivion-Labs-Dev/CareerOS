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

PRIMARY_RESUME_PATH = Path(r"D:\3 - Resources\Docs\Interview\Resume\Akshay_Borse_Resume.pdf")
FALLBACK_RESUME_PATH = Path(__file__).resolve().parents[3] / "data" / "Akshay_Borse_Resume.pdf"


def get_active_resume_path(profile: dict[str, Any]) -> str:
    candidate_path = profile.get("resumePath")
    if candidate_path and Path(candidate_path).exists():
        return str(Path(candidate_path).resolve())
    if PRIMARY_RESUME_PATH.exists():
        return str(PRIMARY_RESUME_PATH.resolve())
    if FALLBACK_RESUME_PATH.exists():
        return str(FALLBACK_RESUME_PATH.resolve())
    return ""


async def _extract_dom_form_state(page: Page) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract full DOM state of all form inputs, comboboxes, and validation errors."""
    js_code = """
    () => {
        var fields = [];
        var errors = [];
        
        var errEls = document.querySelectorAll('.error, [role="alert"], [aria-live="polite"], .field__error, .field__error-text, .text-error, .input-error, .invalid-feedback, p.error, p[id*="error" i], span[id*="error" i], div[id*="error" i], p[class*="error" i], span[class*="error" i]');
        for (var e = 0; e < errEls.length; e++) {
            var txt = (errEls[e].innerText || '').trim();
            if (txt && errors.indexOf(txt) === -1 && errEls[e].offsetParent !== null && txt.toLowerCase().indexOf('cookie') === -1) {
                errors.push(txt);
            }
        }
        // Also look for common ATS inline validation text nodes
        var allTextNodes = document.querySelectorAll('p, span, div, label');
        for (var t = 0; t < allTextNodes.length; t++) {
            var nodeTxt = (allTextNodes[t].innerText || '').trim();
            var normalizedError = nodeTxt.toLowerCase();
            var isValidationMessage = normalizedError === 'this field is required.' ||
                normalizedError.indexOf('please enter your') === 0 ||
                normalizedError.indexOf('please select') === 0 ||
                normalizedError.indexOf('please upload') === 0 ||
                normalizedError.indexOf('please answer') === 0 ||
                normalizedError.indexOf('must select') !== -1 ||
                normalizedError.indexOf('is required') !== -1;
            if (isValidationMessage && nodeTxt.length < 500) {
                if (allTextNodes[t].offsetParent !== null && errors.indexOf(nodeTxt) === -1) {
                    errors.push(nodeTxt);
                }
            }
        }

        var elements = document.querySelectorAll('input:not([type="hidden"]), textarea:not(.g-recaptcha-response):not([name*="recaptcha"]), select, [role="combobox"]');
        for (var i = 0; i < elements.length; i++) {
            var el = elements[i];
            var id = el.id || '';
            var name = el.name || el.getAttribute('name') || '';
            var ariaLabel = el.getAttribute('aria-label') || '';
            var isCombobox = el.getAttribute('role') === 'combobox';
            
            if (id.indexOf('recaptcha') !== -1 || name.indexOf('recaptcha') !== -1 || el.className.indexOf('g-recaptcha-response') !== -1) {
                continue;
            }

            var label = '';
            if (id) {
                try {
                    var l = document.querySelector('label[for="' + id + '"]');
                    if (l) label = l.innerText;
                } catch(err) {}
            }
            if (!label) {
                var parent = el.closest('.field, [data-qa], .form-group, .eeoc__question__wrapper, fieldset, div');
                if (parent) {
                    var pl = parent.querySelector('label, .label, .field__label, legend, p.label');
                    if (pl) label = pl.innerText;
                    else label = (parent.innerText || '').split('\\n')[0];
                }
            }
            label = (label || ariaLabel || name || id).trim();

            var inputType = (el.type || '').toLowerCase();
            var val = el.value || '';
            if (inputType === 'radio') {
                var checkedRadio = name ? document.querySelector('input[type="radio"][name="' + name + '"]:checked') : (el.checked ? el : null);
                val = checkedRadio ? (checkedRadio.value || 'checked') : '';
            } else if (inputType === 'checkbox') {
                val = el.checked ? (el.value || 'checked') : '';
            }
            if (el.tagName.toLowerCase() === 'select') {
                val = (el.options && el.selectedIndex >= 0) ? (el.options[el.selectedIndex].text || '') : '';
            }

            if (isCombobox) {
                var wrapper = el.closest('.select__control, .field-wrapper, .eeoc__question__wrapper, .field, .custom-question') || el.parentElement;
                if (wrapper) {
                    var singleValue = wrapper.querySelector('.select__single-value, [class*="singleValue"], div[class*="single-value"]');
                    if (singleValue) {
                        val = (singleValue.innerText || '').trim();
                    } else {
                        var control = wrapper.querySelector('.select__control') || wrapper;
                        var controlText = (control.innerText || '').trim();
                        if (controlText && controlText.toLowerCase().indexOf('select...') === -1 && controlText.toLowerCase().indexOf('choose') === -1) {
                            val = controlText.split('\\n')[0].trim();
                        }
                    }
                }
            }

            // Some Greenhouse custom questions expose requiredness only after
            // validation, via aria-invalid. Treat those as required so the
            // pre-submit healer gets a chance to resolve them.
            var isRequired = el.required || el.getAttribute('aria-required') === 'true' || el.getAttribute('aria-invalid') === 'true' || label.indexOf('*') !== -1;

            fields.push({
                idx: i,
                id: id,
                name: name,
                label: label,
                type: el.type || '',
                tag: el.tagName.toLowerCase(),
                isCombobox: isCombobox,
                checked: !!el.checked,
                required: isRequired,
                value: val
            });
        }

        return { fields: fields, errors: errors };
    }
    """
    try:
        data = await page.evaluate(js_code)
        return data.get("fields", []), data.get("errors", [])
    except Exception as ex:
        logger.warning("Error extracting DOM state: %s", ex)
        return [], []


async def _select_react_combobox(page: Any, cb_id: str, search_text: str) -> str:
    """Safely and reliably select an option from a React Select combobox or custom dropdown."""
    try:
        # Find input or wrapper
        cb_el = page.locator(f"#{cb_id}").first
        if await cb_el.count() == 0:
            cb_el = page.locator(f'[id*="{cb_id}"]').first
        if await cb_el.count() == 0:
            return ""

        await cb_el.scroll_into_view_if_needed()

        # Locate the surrounding control or wrapper
        wrapper = page.locator(f'div.select__control:has(#{cb_id}), div[class*="control"]:has(#{cb_id}), div:has(> div > #{cb_id}), div:has(> #{cb_id})').first
        target = wrapper if await wrapper.count() > 0 else cb_el

        # Click to open the dropdown menu
        await target.click(force=True)
        await asyncio.sleep(0.3)

        # Look for visible options in the document
        options_loc = page.locator('.select__option, div[class*="option"], [role="option"]')
        opt_count = await options_loc.count()

        if opt_count > 0:
            # 1. Look for exact or partial case-insensitive match
            clean_search = search_text.strip().lower()
            best_opt = None
            first_valid_opt = None
            first_valid_text = ""

            for i in range(opt_count):
                opt = options_loc.nth(i)
                if not await opt.is_visible():
                    continue
                opt_text = (await opt.inner_text()).strip()
                if not opt_text or opt_text.lower() in ("select...", "select", "--", "choose"):
                    continue
                if not first_valid_opt:
                    first_valid_opt = opt
                    first_valid_text = opt_text

                if clean_search and (clean_search in opt_text.lower() or opt_text.lower() in clean_search):
                    best_opt = opt
                    best_text = opt_text
                    break

            target_to_click = best_opt or first_valid_opt
            if target_to_click:
                selected_val = best_text if best_opt else first_valid_text
                await target_to_click.click(force=True)
                await asyncio.sleep(0.2)
                return selected_val

        # Fallback: type only if text-fillable (never on file or hidden inputs)
        try:
            el_type = (await cb_el.get_attribute("type") or "").lower()
            if el_type != "file":
                await cb_el.fill("")
                await cb_el.type(str(search_text), delay=20)
                await asyncio.sleep(0.2)
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.1)
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.2)
                return search_text
        except Exception:
            return ""
        return ""
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
                    await el.fill(str(value))
                    return True
        except Exception:
            continue
    return False


async def _select_radio_option(page_or_frame: Any, field_id: str, value: str) -> bool:
    """Choose a radio option by its exact/partial visible label without guessing."""
    try:
        source = page_or_frame.locator(f"#{field_id}").first
        if await source.count() == 0:
            return False
        name = await source.get_attribute("name")
        if not name:
            return False
        radios = page_or_frame.locator(f'input[type="radio"][name="{name}"]')
        wanted = value.strip().lower()
        for index in range(await radios.count()):
            radio = radios.nth(index)
            radio_id = await radio.get_attribute("id") or ""
            option_value = (await radio.get_attribute("value") or "").strip()
            label = ""
            if radio_id:
                option_label = page_or_frame.locator(f'label[for="{radio_id}"]').first
                if await option_label.count() > 0:
                    label = (await option_label.inner_text()).strip()
            candidates = (option_value.lower(), label.lower())
            if wanted and any(wanted == candidate or wanted in candidate or candidate in wanted for candidate in candidates if candidate):
                await radio.check()
                return True
    except Exception as exc:
        logger.debug("Radio selection error for %s: %s", field_id, exc)
    return False


async def _fill_all_greenhouse_comboboxes(
    page: Any,
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Deterministically fill and select all Greenhouse dropdowns & React Select controls."""
    filled: dict[str, str] = {}

    # Locate all combobox input triggers & select containers
    cb_elements = await page.locator('input[role="combobox"], div.select__control, div[class*="select__control"]').all()

    for el in cb_elements:
        try:
            if not await el.is_visible():
                continue

            # Determine field label
            lbl_text = await el.evaluate("""el => {
                var p = el.closest('div.field, div.custom-question, div[class*="question"], div[class*="field"], fieldset');
                if (p) {
                    var l = p.querySelector('label, legend, p.label, span.label');
                    if (l) return l.innerText.trim();
                    return p.innerText.split('\\n')[0].trim();
                }
                return el.getAttribute('aria-label') || el.id || '';
            }""")
            lbl_lower = (lbl_text or "").lower()
            if not lbl_lower:
                continue

            # Target answer heuristics
            target_text = "No"
            if "phone" in lbl_lower or "country code" in lbl_lower or "country" in lbl_lower and ("code" in lbl_lower or "+1" in lbl_lower):
                target_text = "United States"
            elif "country" in lbl_lower or "countries where we are accepting" in lbl_lower or "based in any of these countries" in lbl_lower:
                target_text = "United States"
            elif "relocate" in lbl_lower or "local to" in lbl_lower or "willing to" in lbl_lower:
                target_text = "Yes"
            elif "transcript" in lbl_lower or "academic transcript" in lbl_lower:
                target_text = "Yes"
            elif "gpa" in lbl_lower or "grade point" in lbl_lower:
                target_text = "3.5"
            elif "english" in lbl_lower or "language" in lbl_lower or "proficiency" in lbl_lower:
                target_text = "Fluent"
            elif "clearance eligibility" in lbl_lower or "obtain and maintain" in lbl_lower or "eligibility to obtain" in lbl_lower:
                target_text = "Yes, I am eligible"
            elif "clearance level" in lbl_lower or "clearance level have you held" in lbl_lower or "security clearance" in lbl_lower:
                target_text = "No clearance held"
            elif "export control" in lbl_lower or "u.s. export" in lbl_lower or "itar" in lbl_lower or "ear" in lbl_lower:
                target_text = "U.S. Citizen"
            elif "work authorization" in lbl_lower or "authorized to work" in lbl_lower or "legally authorized" in lbl_lower or "permanent authorization" in lbl_lower or "authorization to work" in lbl_lower:
                target_text = "Yes"
            elif "sponsorship" in lbl_lower or "require visa" in lbl_lower or "require sponsorship" in lbl_lower or "visa sponsorship" in lbl_lower:
                target_text = "No"
            elif "live in one of the following states" in lbl_lower or "following states" in lbl_lower or "state residency" in lbl_lower:
                target_text = "No"
            elif "privacy notice" in lbl_lower or "job applicant privacy" in lbl_lower or "acknowledge that i have read" in lbl_lower or "terms" in lbl_lower or "consent" in lbl_lower:
                target_text = "Yes"
            elif "double-check all the information" in lbl_lower or "accuracy is crucial" in lbl_lower or "errors or omissions" in lbl_lower or "accurate" in lbl_lower:
                target_text = "Yes"
            elif "history with" in lbl_lower or "employed by" in lbl_lower or "conflict" in lbl_lower or "previously applied" in lbl_lower or "family member" in lbl_lower or "relative" in lbl_lower or "government" in lbl_lower:
                target_text = "No"
            elif "notice period" in lbl_lower or "start date" in lbl_lower or "available to start" in lbl_lower:
                target_text = "Immediately"
            elif "how did you hear" in lbl_lower or "source" in lbl_lower or "referral" in lbl_lower or "where did you first hear" in lbl_lower:
                target_text = "LinkedIn"
            elif "gender" in lbl_lower:
                target_text = "Decline"
            elif "transgender" in lbl_lower:
                target_text = "Decline"
            elif "sexual orientation" in lbl_lower:
                target_text = "Decline"
            elif "hispanic" in lbl_lower or "latino" in lbl_lower:
                target_text = "No"
            elif "race" in lbl_lower or "ethnicity" in lbl_lower:
                target_text = "Asian"
            elif "veteran" in lbl_lower:
                target_text = "not a protected"
            elif "disability" in lbl_lower:
                target_text = "do not have"
            else:
                if answer_lib:
                    for a in answer_lib:
                        q_cand = str(a.get("questionText") or "").lower()
                        if q_cand and (q_cand in lbl_lower or lbl_lower in q_cand):
                            target_text = str(a.get("answer") or "No")
                            break

            await el.scroll_into_view_if_needed()
            await el.click(force=True)
            await asyncio.sleep(0.2)

            options_loc = page.locator('.select__option, div[class*="option"], [role="option"]')
            opt_count = await options_loc.count()

            matched = False
            first_opt = None
            first_opt_text = ""

            for i in range(opt_count):
                opt = options_loc.nth(i)
                if not await opt.is_visible():
                    continue
                otxt = (await opt.inner_text()).strip()
                if not otxt or otxt.lower() in ("select...", "select", "--", "choose"):
                    continue
                if not first_opt:
                    first_opt = opt
                    first_opt_text = otxt

                if target_text.lower() in otxt.lower() or otxt.lower() in target_text.lower():
                    await opt.click(force=True)
                    filled[lbl_text[:35]] = otxt
                    matched = True
                    await asyncio.sleep(0.1)
                    break

            if not matched and first_opt:
                await first_opt.click(force=True)
                filled[lbl_text[:35]] = first_opt_text
                await asyncio.sleep(0.1)

        except Exception as ex:
            logger.debug("Combobox error: %s", ex)

    return filled


async def _fill_standard_and_react_fields(
    page: Any,
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None,
    company: str,
    title: str,
    resume_file: str,
    log_cb: Any = None,
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

    # Handle Greenhouse/Custom Phone Country Code selector
    country_dropdown = page.locator('button[aria-label*="Country" i], div.select__control:has(input[id*="country" i]), [aria-label="Country Code"], div.phone-input__country').first
    if await country_dropdown.count() > 0 and await country_dropdown.is_visible():
        try:
            await country_dropdown.click(force=True)
            await asyncio.sleep(0.2)
            us_opt = page.locator('.select__option:has-text("United States"), [role="option"]:has-text("United States"), li:has-text("United States")').first
            if await us_opt.count() > 0:
                await us_opt.click(force=True)
                await asyncio.sleep(0.1)
        except Exception:
            pass

    phone = profile.get("phone", "425-336-9852")
    phone_clean = re.sub(r"[^\d]", "", phone)
    if len(phone_clean) == 10:
        phone_formatted = f"({phone_clean[:3]}) {phone_clean[3:6]}-{phone_clean[6:]}"
    else:
        phone_formatted = phone

    if await _fill_first_visible(
        page,
        ["#phone", "input[name='job_application[phone]']", "#job_application_phone", "input[name*='phone' i]", "input[type='tel']"],
        phone_formatted
    ):
        filled["Phone"] = phone_formatted

    # Fill Location (City) if requested
    loc_inputs = page.locator('input[id*="location" i], input[name*="location" i], input[placeholder*="location" i], input[id*="candidate_location" i]')
    if await loc_inputs.count() > 0:
        city_val = profile.get("location") or "San Francisco, CA, USA"
        for i in range(await loc_inputs.count()):
            loc_el = loc_inputs.nth(i)
            if await loc_el.is_visible():
                try:
                    await loc_el.fill(city_val)
                    filled["Location"] = city_val
                    await asyncio.sleep(0.2)
                    # If auto-suggest popup appears, pick first
                    first_sug = page.locator('.location-suggestion, [role="option"], .pac-item').first
                    if await first_sug.count() > 0 and await first_sug.is_visible():
                        await first_sug.click(force=True)
                except Exception:
                    pass

    if log_cb and (filled.get("First Name") or filled.get("Email")):
        log_cb(f"Filled contact info ({first} {last}, {email})")

    # 2. Resume File
    file_inputs = await page.locator('input[type="file"]').all()
    if file_inputs and resume_file and os.path.exists(resume_file):
        try:
            await file_inputs[0].set_input_files(resume_file)
            filled["Resume"] = os.path.basename(resume_file)
            if log_cb:
                log_cb(f"Attached resume ({os.path.basename(resume_file)})")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("Resume attach error: %s", e)

    # 3. React Comboboxes
    if log_cb:
        log_cb("Resolving dropdowns & comboboxes (EEOC / Custom)...")
    cb_filled = await _fill_all_greenhouse_comboboxes(page, profile, answer_lib)
    filled.update(cb_filled)
    if log_cb and cb_filled:
        log_cb(f"Selected {len(cb_filled)} combobox & dropdown options")

    # 4. Textareas & Long Essay Answers
    textareas = await page.locator('textarea:not(.g-recaptcha-response):not([name*="recaptcha"])').all()
    for ta in textareas:
        try:
            if not await ta.is_visible():
                continue
            ta_lbl = ""
            ta_id = await ta.get_attribute("id") or ""
            if ta_id:
                lbl_el = page.locator(f'label[for="{ta_id}"]').first
                if await lbl_el.count() > 0:
                    ta_lbl = await lbl_el.inner_text()
            if not ta_lbl:
                parent = ta.locator('xpath=ancestor::div[contains(@class, "field") or contains(@class, "form-group")][1]').first
                if await parent.count() > 0:
                    ta_lbl = await parent.inner_text()
            ta_lbl_lower = ta_lbl.lower()

            curr_val = (await ta.input_value()).strip()
            if curr_val:
                continue

            essay_ans = "Yes, extensive production experience with modern distributed systems, TypeScript, React, Next.js, and AI workflows."
            if "react" in ta_lbl_lower or "next" in ta_lbl_lower:
                essay_ans = "Yes, over 6+ years of production experience building high-performance applications with React, Next.js, and TypeScript."
            elif "ai" in ta_lbl_lower or "agent" in ta_lbl_lower or "llm" in ta_lbl_lower:
                essay_ans = "Strong background building AI-powered applications, agent workflows, tool orchestration, and LLM integrations using OpenAI and Anthropic APIs."
            elif "blog" in ta_lbl_lower or "article" in ta_lbl_lower or "read in the last 6 months" in ta_lbl_lower:
                essay_ans = "Anthropic's research paper and blog on Building Effective Agents (December 2024), highlighting workflow patterns for agentic tool use and evaluation loops."
            elif "why" in ta_lbl_lower or "interest" in ta_lbl_lower:
                essay_ans = f"Deeply passionate about {company}'s mission and engineering excellence. Excited to contribute to mission-critical systems and high-scale architecture."

            await ta.fill(essay_ans)
            filled[ta_lbl[:30] or "Essay"] = essay_ans[:30] + "..."
        except Exception:
            pass

    # 4. Standard Text Links (LinkedIn, Website, Portfolio)
    if await page.locator('input[id="job_application_answers_attributes_0_text_value"], input[id*="linkedin" i], input[name*="linkedin" i]').count() > 0:
        val = profile.get("linkedin", "https://www.linkedin.com/in/amsborse/")
        await _fill_first_visible(page, ['input[id*="linkedin" i]', 'input[name*="linkedin" i]'], val)
        filled["LinkedIn"] = val

    website_inputs = await page.locator('input[type="text"][id="website"], input[type="text"][name*="website" i], input[type="text"][id*="portfolio" i], input[type="url"]').all()
    for winp in website_inputs:
        w_role = await winp.get_attribute("role") or ""
        if w_role == "combobox":
            continue
        val = profile.get("portfolio") or profile.get("github") or "https://amsborse.github.io/resume"
        try:
            await winp.fill(val)
            filled["Website"] = val
        except Exception:
            pass

    return filled


async def execute_live_playwright_submission(
    job_item: dict[str, Any],
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
    headless: bool = True,
    timeout_sec: float = 75.0,
    log_callback: Any = None,
) -> dict[str, Any]:
    """Execute autonomous browser submission with strict pre-submit and post-submit verification."""
    app_url = job_item.get("applicationUrl") or job_item.get("listingUrl") or ""
    company = job_item.get("company") or "Target Company"
    title = job_item.get("title") or "Target Role"
    job_id = job_item.get("id") or "job"

    if not app_url:
        return {"submitted": False, "error": "Missing application URL", "evidence": {}}

    # If URL is a career hub containing gh_jid parameter, resolve to direct Greenhouse job URL for 100% reliable submission
    if "gh_jid=" in app_url and not ("greenhouse.io" in app_url and "/jobs/" in app_url):
        import urllib.parse
        parsed = urllib.parse.urlparse(app_url)
        qs = urllib.parse.parse_qs(parsed.query)
        gh_jid = qs.get("gh_jid", [None])[0]
        if gh_jid:
            comp_slug = re.sub(r"[^a-zA-Z0-9]", "", company.lower())
            direct_board_url = f"https://job-boards.greenhouse.io/{comp_slug}/jobs/{gh_jid}"
            logger.info("Resolved career hub gh_jid URL %s -> direct Greenhouse URL: %s", app_url, direct_board_url)
            app_url = direct_board_url

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

        # Apply Cloud Stealth Anti-Fingerprinting Profile
        from app.services.application_assistant.stealth_browser_profile import apply_stealth_profile
        await apply_stealth_profile(context, page)

        try:
            logger.info("Navigating to application URL: %s", app_url)
            if log_callback:
                log_callback(f"Navigating to {company} job URL...")
            await page.goto(app_url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
            await asyncio.sleep(2.5)

            # Check if job was closed / unlisted by company and redirected to generic job search / open roles
            current_url_lower = page.url.lower()
            if ("/open-roles" in current_url_lower or "/careers/search" in current_url_lower or "/jobs/search" in current_url_lower) and not any(term in current_url_lower for term in ["/jobs/", "gh_jid="]) or ("404" in await page.title()):
                return {
                    "submitted": False,
                    "expired": True,
                    "error": "Job posting has expired or was removed by company (redirected to general career directory)",
                    "evidence": {
                        "finalUrl": page.url,
                    },
                    "fieldsFilled": {},
                }

            # Check for iframe (e.g. Greenhouse or Lever embeds)
            target_frame: Any = page
            for frame in page.frames:
                if frame != page and any(term in frame.url for term in ["greenhouse.io", "lever.co", "ashby"]):
                    target_frame = frame
                    if log_callback:
                        log_callback(f"Switched to application iframe ({frame.url[:40]}...)")
                    break

            # If application form is not yet visible, check for "Apply" / "Apply for this job" button on overview page
            try:
                form_present = await target_frame.locator('input[name*="name" i], #first_name, #email, form').count() > 0
                if not form_present:
                    apply_btn_selectors = [
                        'a[href*="#apply"]',
                        'a[href*="#application"]',
                        'a:has-text("Apply for this job")',
                        'a:has-text("Apply")',
                        'button:has-text("Apply for this job")',
                        'button:has-text("Apply")',
                        '[data-qa="apply-button"]',
                        '.btn-apply',
                    ]
                    for ab_sel in apply_btn_selectors:
                        ab = page.locator(ab_sel).first
                        if await ab.count() > 0 and await ab.is_visible():
                            logger.info("Clicking initial Apply button (%s) to open application form...", ab_sel)
                            if log_callback:
                                log_callback(f"Clicking '{ab_sel}' to expose application form...")
                            await ab.click()
                            await asyncio.sleep(2.0)
                            break
            except Exception as ex:
                logger.debug("Apply button click check: %s", ex)

            # Initial Form Filling
            filled_fields = await _fill_standard_and_react_fields(
                page=target_frame,
                profile=profile,
                answer_lib=answer_lib,
                company=company,
                title=title,
                resume_file=resume_file,
                log_cb=log_callback,
            )

            # ─── PRE-SUBMISSION VERIFICATION & HEALING ─────────────────
            max_healing_rounds = 2
            qwen_approved = False

            for round_num in range(1, max_healing_rounds + 1):
                dom_fields, validation_errors = await _extract_dom_form_state(target_frame)

                # Fast deterministic check: if form is clean and error-free, approve in <5ms
                missing_req = [
                    f for f in dom_fields
                    if (f.get("required") or "*" in f.get("label", ""))
                    and not f.get("value")
                    and (f.get("type") or "").lower() != "file"
                ]

                if not validation_errors and not missing_req:
                    logger.info("Deterministic Pre-Submission Review: 100% APPROVED (0 errors, 0 missing required)")
                    if log_callback:
                        log_callback(f"Deterministic Pre-Submission Audit: 100% PASS [OK] (Instant <5ms)")
                    qwen_approved = True
                    break

                logger.info("Form requires review/healing (Round %d/%d)...", round_num, max_healing_rounds)
                if log_callback:
                    log_callback(f"Form Review & Healing (Round {round_num}/{max_healing_rounds})...")

                review_res = await review_and_heal_form_state(
                    form_state=dom_fields,
                    validation_errors=validation_errors,
                    profile=profile,
                    company=company,
                    title=title,
                )

                if review_res.get("readyToSubmit") and not validation_errors:
                    logger.info("Form Review: 100% APPROVED [OK]")
                    if log_callback:
                        log_callback(f"Form Review: 100% APPROVED [OK] (Round {round_num})")
                    qwen_approved = True
                    break

                # Self-Healing Action: Repair missing or invalid fields
                missing_fields = review_res.get("missingOrInvalidFields", [])
                logger.warning("Qwen Review detected %d items requiring self-healing in round %d", len(missing_fields), round_num)
                if log_callback:
                    log_callback(f"Auto-healing {len(missing_fields)} field(s) (Round {round_num})...", lvl="warning")

                for item in missing_fields:
                    f_id = item.get("fieldId")
                    f_label = item.get("label", "")
                    f_label_lower = f_label.lower()
                    fix_val = item.get("suggestedFixValue")

                    # Instant deterministic resolution for high-frequency questions
                    if not fix_val:
                        if "gender" in f_label_lower:
                            fix_val = profile.get("gender") or "Man"
                        elif "hispanic" in f_label_lower or "latino" in f_label_lower:
                            fix_val = profile.get("hispanic") or "No"
                        elif "race" in f_label_lower or "ethnicity" in f_label_lower:
                            fix_val = profile.get("race") or "Asian"
                        elif "veteran" in f_label_lower:
                            fix_val = "I am not a protected veteran"
                        elif "disability" in f_label_lower:
                            fix_val = "I do not have a disability"
                        elif "transcript" in f_label_lower or "academic transcript" in f_label_lower:
                            fix_val = "Yes"
                        elif "relocate" in f_label_lower or "local to" in f_label_lower:
                            fix_val = "Yes"
                        elif "clearance eligibility" in f_label_lower or "obtain and maintain" in f_label_lower or "eligibility to obtain" in f_label_lower:
                            fix_val = "Yes, I am eligible"
                        elif "clearance level" in f_label_lower or "clearance level have you held" in f_label_lower or "security clearance" in f_label_lower:
                            fix_val = "No clearance held"
                        elif "export control" in f_label_lower or "u.s. export" in f_label_lower or "itar" in f_label_lower or "ear" in f_label_lower:
                            fix_val = "U.S. Citizen"
                        elif "work authorization" in f_label_lower or "authorized to work" in f_label_lower:
                            fix_val = "Yes"
                        elif "sponsorship" in f_label_lower or "require visa" in f_label_lower:
                            fix_val = "No"
                        elif "conflict" in f_label_lower or "history with" in f_label_lower or "employed by" in f_label_lower:
                            fix_val = "No"
                        elif "how did you hear" in f_label_lower or "source" in f_label_lower:
                            fix_val = "LinkedIn"
                        else:
                            # Instant hash lookup in answer library before LLM
                            if answer_lib:
                                for a in answer_lib:
                                    q_cand = str(a.get("questionText") or "").lower()
                                    if q_cand and (q_cand in f_label_lower or f_label_lower in q_cand):
                                        fix_val = str(a.get("answer") or "No")
                                        break
                    if f_id:
                        elem = target_frame.locator(f"#{f_id}").first
                        if await elem.count() > 0:
                            try:
                                el_type = (await elem.evaluate("el => (el.type || el.getAttribute('type') || '').toLowerCase()")) or ""
                                is_cb = await elem.get_attribute("role") == "combobox"

                                if el_type == "file":
                                    if resume_file and os.path.exists(resume_file):
                                        try:
                                            await elem.set_input_files(resume_file)
                                            filled_fields[f_label or f_id] = os.path.basename(resume_file)
                                            if log_callback:
                                                log_callback(f"Attached file for [{f_label or f_id}] ({os.path.basename(resume_file)})")
                                        except Exception as f_err:
                                            logger.warning("File attachment error on %s: %s", f_id, f_err)
                                elif is_cb:
                                    await _select_react_combobox(target_frame, f_id, str(fix_val))
                                    filled_fields[f_label or f_id] = str(fix_val)
                                    if log_callback:
                                        log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                                elif el_type == "radio":
                                    if fix_val and await _select_radio_option(target_frame, f_id, str(fix_val)):
                                        filled_fields[f_label or f_id] = str(fix_val)
                                        if log_callback:
                                            log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                                else:
                                    # Never coerce an unknown field to the literal string
                                    # "None". Leaving it unresolved prevents a bad submit.
                                    if fix_val:
                                        await elem.fill(str(fix_val))
                                        filled_fields[f_label or f_id] = str(fix_val)
                                        if log_callback:
                                            log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                            except Exception as fill_err:
                                logger.warning("Fill error on %s: %s", f_id, fill_err)



                await asyncio.sleep(0.5)

            # Submission is a hard boundary: do not click Submit when the form
            # still contains required fields or visible validation errors. The
            # previous implementation recorded a misleading post-submit failure
            # after clicking through an incomplete Greenhouse form.
            final_fields, final_validation_errors = await _extract_dom_form_state(target_frame)
            final_missing_required = [
                field for field in final_fields
                if (field.get("required") or "*" in field.get("label", ""))
                and not field.get("value")
            ]
            if final_validation_errors or final_missing_required:
                unresolved = [field.get("label") or field.get("id") or "unnamed field" for field in final_missing_required]
                reason_parts = []
                if unresolved:
                    reason_parts.append(f"Required fields remain unresolved: {', '.join(unresolved[:8])}")
                if final_validation_errors:
                    reason_parts.append(f"Form validation errors: {', '.join(final_validation_errors[:5])}")
                error = "; ".join(reason_parts) or "Form did not pass pre-submit validation"
                logger.warning("Blocking incomplete application submission: %s", error)
                if log_callback:
                    log_callback("Submission paused: the form still needs verified answers.", lvl="warning")
                pre_screenshot_path = SCREENSHOTS_DIR / f"{job_id}_presubmit.png"
                try:
                    await page.screenshot(path=str(pre_screenshot_path), full_page=True)
                except Exception:
                    pass
                return {
                    "submitted": False,
                    "error": error,
                    "evidence": {
                        "preSubmitValidationErrors": final_validation_errors,
                        "unresolvedRequiredFields": unresolved,
                        "preScreenshotPath": str(pre_screenshot_path.resolve()) if pre_screenshot_path.exists() else "",
                    },
                    "fieldsFilled": filled_fields,
                }

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
                'a:has-text("Submit Application")',
                '[role="button"]:has-text("Submit")',
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
            if log_callback:
                log_callback(f"Clicking final Submit button on {company}...")
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

            # ─── STRICT QWEN POST-SUBMISSION PROOF VALIDATION ───────────────────
            body_text = await page.inner_text("body")
            
            # Check for visible validation errors and whether form/submit button is still present on page
            _, active_errors = await _extract_dom_form_state(target_frame)
            
            form_still_visible = False
            submit_btn_still_visible = False
            try:
                form_el = target_frame.locator('form, #application_form, #apply_form').first
                form_still_visible = await form_el.count() > 0 and await form_el.is_visible()
                if submit_button:
                    submit_btn_still_visible = await submit_button.count() > 0 and await submit_button.is_visible()
            except Exception:
                pass

            from app.services.application_assistant.qwen_form_reviewer import verify_submission_confirmation

            qwen_confirmation = await verify_submission_confirmation(
                body_text=body_text,
                confirmation_url=confirmation_url,
                active_errors=active_errors,
                company=company,
                title=title,
                form_still_visible=form_still_visible,
                submit_button_visible=submit_btn_still_visible,
            )

            is_genuine_submission = qwen_confirmation.get("submissionConfirmed", False)

            if not is_genuine_submission:
                err_msg = qwen_confirmation.get("reason") or "ATS rejected submission or required fields remain incomplete"
                logger.error("Submission unconfirmed by Qwen verification: %s", err_msg)
                return {
                    "submitted": False,
                    "error": err_msg,
                    "evidence": {
                        "confirmationUrl": confirmation_url,
                        "screenshotPath": str(post_screenshot_path.resolve()),
                        "preScreenshotPath": str(pre_screenshot_path.resolve()),
                        "errorsFound": active_errors,
                        "qwenReview": qwen_confirmation,
                    },
                    "fieldsFilled": filled_fields,
                }

            conf_msg = qwen_confirmation.get("confirmationMessage") or "Application submitted successfully"

            # Archive immutable submission receipt
            from app.services.application_assistant.submission_receipt_service import create_submission_receipt
            receipt = create_submission_receipt(
                job_id=job_id,
                company=company,
                title=title,
                application_url=app_url,
                confirmation_url=confirmation_url,
                confirmation_text=conf_msg,
                fields_filled=filled_fields,
                presubmit_screenshot_path=str(pre_screenshot_path.resolve()) if pre_screenshot_path.exists() else "",
                confirmation_screenshot_path=str(post_screenshot_path.resolve()) if post_screenshot_path.exists() else "",
                qwen_review=qwen_confirmation,
            )

            return {
                "submitted": True,
                "evidence": {
                    "confirmationText": conf_msg,
                    "confirmationUrl": confirmation_url,
                    "screenshotPath": str(post_screenshot_path.resolve()),
                    "preScreenshotPath": str(pre_screenshot_path.resolve()),
                    "qwenPreApproved": qwen_approved,
                    "qwenPostApproved": True,
                    "qwenReview": qwen_confirmation,
                    "receipt": receipt,
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
