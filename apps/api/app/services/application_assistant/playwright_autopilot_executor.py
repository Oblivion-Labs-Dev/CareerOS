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
from app.services.application_assistant.question_classifier import (
    QuestionType,
    classify_question,
    classify_free_text_intent,
    is_sensitive_factual,
)
from app.services.application_assistant.profile_answer_resolver import (
    resolve_answer,
    AnswerResolution,
)
from app.services.application_assistant.cross_field_validator import (
    validate_answers,
    ValidationReport,
)
from app.services.application_assistant.form_field_persistence import (
    persist_discovered_form,
    persist_answer_resolutions,
    persist_pre_submit_report,
)
from app.services.application_assistant.browser_verifier import verify_browser_dom_state
from app.services.application_assistant.submission_policy import SubmissionPolicy, SubmissionDecision
from app.services.tracking_email import derive_contact_email

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
        
        var errEls = document.querySelectorAll('.error, [role="alert"]:not([aria-live="polite"]), .field__error, .field__error-text, .text-error, .input-error, .invalid-feedback, p.error, p[id*="error" i], span[id*="error" i], div[id*="error" i], p[class*="error" i], span[class*="error" i]');
        for (var e = 0; e < errEls.length; e++) {
            var txt = (errEls[e].innerText || '').trim();
            if (txt && errors.indexOf(txt) === -1 && errEls[e].offsetParent !== null && txt.toLowerCase().indexOf('cookie') === -1) {
                // Ignore screen-reader option selection announcements (e.g. from React-Select or ARIA comboboxes)
                var normLower = txt.toLowerCase();
                if (normLower.indexOf('option ') === 0 || normLower.indexOf(', selected.') !== -1 || normLower === 'selected.') {
                    continue;
                }
                errors.push(txt);
            }
        }
        // Also look for common ATS inline validation text nodes (excluding form labels and question legends)
        var allTextNodes = document.querySelectorAll('p, span, div');
        for (var t = 0; t < allTextNodes.length; t++) {
            var node = allTextNodes[t];
            if (node.closest('label, legend, .label, .field__label, .question-label') !== null) {
                continue;
            }
            var nodeTxt = (node.innerText || '').trim();
            var normalizedError = nodeTxt.toLowerCase();
            // Exclude screen-reader selection announcements and large marketing blocks
            if (normalizedError.indexOf('option ') === 0 || normalizedError.indexOf(', selected.') !== -1 || normalizedError.indexOf('*') !== -1) {
                continue;
            }
            var isValidationMessage = normalizedError === 'this field is required.' ||
                normalizedError === 'this field is required' ||
                normalizedError.indexOf('please enter a valid') === 0 ||
                normalizedError.indexOf('please select an option') === 0 ||
                normalizedError.indexOf('please select a valid') === 0 ||
                normalizedError.indexOf('please upload a') === 0 ||
                normalizedError.indexOf('please answer this') === 0 ||
                normalizedError.indexOf('must select an option') !== -1 ||
                normalizedError.indexOf('is required.') !== -1;
            if (isValidationMessage && nodeTxt.length < 150) {
                if (node.offsetParent !== null && errors.indexOf(nodeTxt) === -1) {
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
        cb_el = page.locator(f'[id="{cb_id}"]').first
        if await cb_el.count() == 0:
            cb_el = page.locator(f'[id*="{cb_id}"]').first
        if await cb_el.count() == 0:
            return ""

        await cb_el.scroll_into_view_if_needed()

        # Locate the surrounding control or wrapper
        wrapper = page.locator(f'div.select__control:has([id="{cb_id}"]), div[class*="control"]:has([id="{cb_id}"]), div:has(> div > [id="{cb_id}"]), div:has(> [id="{cb_id}"])').first
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
    """Fill all Greenhouse dropdowns & React Select controls using the centralized resolver."""
    filled: dict[str, str] = {}
    all_resolutions: list[AnswerResolution] = []

    cb_elements = await page.locator('input[role="combobox"]').all()

    for el in cb_elements:
        try:
            cid = await el.get_attribute("id") or ""
            if cid == "iti-0__search-input":
                continue

            if not await el.is_visible():
                continue

            # Determine field label
            lbl_text = await el.evaluate("""el => {
                var id = el.id;
                if (id) {
                    try {
                        var l = document.querySelector('label[for="' + id + '"]');
                        if (l && l.innerText && l.innerText.trim()) return l.innerText.trim();
                    } catch(e) {}
                }
                var cur = el.parentElement;
                while (cur && cur.tagName !== 'FORM' && cur.tagName !== 'BODY') {
                    var l = cur.querySelector('label, legend, .label, [class*="label"], p');
                    if (l && l.innerText && l.innerText.trim() && l.innerText.trim().length > 3) {
                        return l.innerText.trim();
                    }
                    cur = cur.parentElement;
                }
                return el.getAttribute('aria-label') || el.name || el.id || '';
            }""")
            if not (lbl_text or "").strip():
                continue

            # Locate surrounding React-Select container or the input itself
            wrapper = page.locator(f'div.select__control:has([id="{cid}"]), div[class*="control"]:has([id="{cid}"])').first
            target_to_open = wrapper if await wrapper.count() > 0 else el

            # Collect available options by opening the dropdown
            await target_to_open.scroll_into_view_if_needed()
            await target_to_open.click(force=True)
            await asyncio.sleep(0.2)

            # Fast evaluate to get all option texts in 1 ms without slow per-element Playwright RPCs
            opt_data: list[str] = await page.evaluate("""() => {
                var opts = document.querySelectorAll('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option, [role="option"]');
                var res = [];
                for (var i = 0; i < opts.length; i++) {
                    var t = (opts[i].innerText || '').trim();
                    if (t && opts[i].offsetParent !== null && t.toLowerCase().indexOf('select...') === -1 && t.toLowerCase().indexOf('choose') === -1) {
                        res.push(t);
                    }
                }
                return res;
            }""")

            available_options: list[str] = opt_data or []

            if not available_options:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.05)
                continue

            # ── Check if this is a country code dropdown (over 100 country options) ──
            is_country_code = len(available_options) > 100 and any("+1" in o or "united states" in o.lower() for o in available_options)
            effective_q_text = "Country Code" if is_country_code else lbl_text

            # ── Centralized resolution (replaces all if/elif heuristics) ──
            resolution = resolve_answer(
                question_text=effective_q_text,
                profile=profile,
                options=available_options,
                answer_lib=answer_lib,
            )
            all_resolutions.append(resolution)

            target_text = resolution.answer
            if not target_text:
                logger.info("Combobox '%s' unresolved (type=%s), skipping", lbl_text[:50], resolution.question_type)
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.05)
                continue

            if resolution.blocking_errors:
                logger.warning("Combobox '%s' blocked: %s", lbl_text[:50], resolution.blocking_errors)
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.05)
                continue

            # Find and click the matching option by text
            matched = False
            target_lower = target_text.strip().lower()

            # 1. Exact or partial match click via fast locator
            for opt_str in available_options:
                if target_lower == opt_str.lower() or target_lower in opt_str.lower() or opt_str.lower() in target_lower:
                    if target_lower == "male" and "female" in opt_str.lower():
                        continue
                    opt_to_click = page.locator(f'.select__option, [role="option"]').filter(has_text=opt_str).first
                    if await opt_to_click.count() > 0:
                        await opt_to_click.click(force=True)
                        filled[lbl_text[:50]] = opt_str
                        matched = True
                        await asyncio.sleep(0.1)
                        break

            # 2. Dynamic typing pass for searchable/async comboboxes (e.g. School, Major)
            if not matched and target_text:
                try:
                    await el.click(force=True)
                    await page.keyboard.type(target_text, delay=20)
                    await asyncio.sleep(0.3)

                    first_opt = page.locator('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option').first
                    if await first_opt.count() > 0 and await first_opt.is_visible():
                        f_txt = (await first_opt.inner_text()).strip()
                        if f_txt and f_txt.lower() not in ("no options", "select..."):
                            await first_opt.click(force=True)
                            filled[lbl_text[:50]] = f_txt
                            matched = True
                            await asyncio.sleep(0.1)
                except Exception as dyn_err:
                    logger.debug("Combobox dynamic search error: %s", dyn_err)

            if not matched:
                logger.warning(
                    "Combobox '%s': target '%s' not found in %d options, skipping (NO random fallback)",
                    lbl_text[:50], target_text, len(available_options),
                )
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.05)

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

    email = derive_contact_email(profile.get("email") or "") or "amsborse+career@gmail.com"
    if await _fill_first_visible(
        page,
        ["#email", "input[name='job_application[email]']", "#job_application_email", "input[name*='email' i]", "form input[type='email']"],
        email
    ):
        filled["Email"] = email

    # Handle Greenhouse/Custom Phone Country Code selector
    country_dropdown = page.locator('.phone-input button[aria-label*="Country" i], [aria-label="Phone Country Code"], div.phone-input__country').first
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
    loc_input = page.locator('input[id*="candidate_location" i], input[id*="location" i], input[name*="location" i]').first
    if await loc_input.count() > 0 and await loc_input.is_visible():
        city_val = profile.get("location") or "Auburn, WA"
        if city_val.strip().lower() in ("akshay", "akshay borse", "none", ""):
            city_val = "Auburn, WA"
        try:
            await loc_input.fill(city_val)
            filled["Location"] = city_val
            await asyncio.sleep(0.3)
            # Many ATS location fields are a Google-Places-style autocomplete: typed
            # text alone doesn't satisfy the required field until a suggestion is
            # actually clicked (or the highlighted one confirmed). Match generically
            # against the parts of city_val — a hardcoded "Auburn, WA"-only match
            # left every other city (i.e. real production usage) unfillable.
            suggestions = page.locator('.location-suggestion, [role="option"], .pac-item, li[class*="suggestion"]')
            sug_count = await suggestions.count()
            city_parts = [p.strip().lower() for p in city_val.split(",") if p.strip()]
            clicked = False
            if sug_count > 0:
                # Prefer a suggestion matching ALL parts (city AND state) over one
                # matching only the city name — "Auburn, WA" was previously matched
                # with a plain `any()`, so the first "Auburn, <wrong state>" in the
                # list (there are several real US cities named Auburn) won over the
                # correct one further down. Fall back to a partial/first-visible
                # match only when no full match exists, so the field still gets
                # something rather than being left uncommitted.
                first_visible_el = None
                partial_match_el = None
                full_match_el = None
                for s_idx in range(min(sug_count, 8)):
                    s_el = suggestions.nth(s_idx)
                    if not await s_el.is_visible():
                        continue
                    s_text = (await s_el.inner_text()).lower()
                    if first_visible_el is None:
                        first_visible_el = s_el
                    if partial_match_el is None and any(part and part in s_text for part in city_parts):
                        partial_match_el = s_el
                    if full_match_el is None and city_parts and all(part in s_text for part in city_parts):
                        full_match_el = s_el
                        break
                best_el = full_match_el or partial_match_el or first_visible_el
                if best_el is not None:
                    await best_el.click(force=True)
                    clicked = True
            if not clicked and sug_count > 0:
                # A suggestion list rendered but nothing matched by text — the
                # highlighted/first option is still far better than leaving the
                # required field uncommitted.
                try:
                    await page.keyboard.press("ArrowDown")
                    await page.keyboard.press("Enter")
                except Exception:
                    pass
        except Exception:
            pass

    if log_cb and (filled.get("First Name") or filled.get("Email")):
        log_cb(f"Filled contact info ({first} {last}, {email})")

    # 2. Resume File
    file_input = page.locator('input[type="file"][name*="resume" i], input[type="file"][id*="resume" i], input[type="file"]').first
    if await file_input.count() > 0 and resume_file and os.path.exists(resume_file):
        try:
            await file_input.set_input_files(resume_file, timeout=5000)
            try:
                await file_input.dispatch_event("change")
                await file_input.dispatch_event("input")
            except Exception:
                pass
            filled["Resume"] = os.path.basename(resume_file)
            if log_cb:
                log_cb(f"Attached resume ({os.path.basename(resume_file)})")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("Resume attach error: %s", e)

    # 3. React Comboboxes & Native Selects
    if log_cb:
        log_cb("Resolving dropdowns & comboboxes (EEOC / Custom)...")
    cb_filled = await _fill_all_greenhouse_comboboxes(page, profile, answer_lib)
    filled.update(cb_filled)

    # Native Select dropdowns (EEOC, custom questions)
    select_elements = await page.locator('select:visible').all()
    for sel_el in select_elements:
        try:
            sel_id = await sel_el.get_attribute("id") or ""
            sel_name = await sel_el.get_attribute("name") or ""
            sel_lbl = ""
            if sel_id:
                lbl_el = page.locator(f'label[for="{sel_id}"]').first
                if await lbl_el.count() > 0:
                    sel_lbl = await lbl_el.inner_text()
            if not sel_lbl:
                parent = sel_el.locator('xpath=ancestor::div[contains(@class, "field") or contains(@class, "custom-question") or contains(@class, "form-group")][1]').first
                if await parent.count() > 0:
                    sel_lbl = (await parent.inner_text()).split('\n')[0]
            if not sel_lbl:
                sel_lbl = await sel_el.get_attribute("aria-label") or sel_name or sel_id

            opt_texts = await sel_el.locator('option').all_inner_texts()
            available = [o.strip() for o in opt_texts if o.strip() and o.strip().lower() not in ("select...", "select", "--", "choose")]

            resolution = resolve_answer(
                question_text=sel_lbl,
                profile=profile,
                options=available,
                answer_lib=answer_lib,
            )
            if resolution.answer and not resolution.blocking_errors:
                for opt_t in available:
                    if resolution.answer.lower() in opt_t.lower() or opt_t.lower() in resolution.answer.lower():
                        await sel_el.select_option(label=opt_t)
                        filled[sel_lbl[:50]] = opt_t
                        break
        except Exception:
            pass

    # Checkboxes (Consent / Demographic / Terms)
    checkbox_elements = await page.locator('input[type="checkbox"]:visible').all()
    for chk in checkbox_elements:
        try:
            chk_id = await chk.get_attribute("id") or ""
            chk_lbl = ""
            if chk_id:
                lbl_el = page.locator(f'label[for="{chk_id}"]').first
                if await lbl_el.count() > 0:
                    chk_lbl = await lbl_el.inner_text()
            if not chk_lbl:
                parent = chk.locator('xpath=ancestor::div[contains(@class, "field") or contains(@class, "form-group") or contains(@class, "checkbox")][1]').first
                if await parent.count() > 0:
                    chk_lbl = await parent.inner_text()

            chk_lbl_low = (chk_lbl or "").lower()
            if any(k in chk_lbl_low for k in ["consent", "agree", "acknowledge", "terms", "privacy", "survey", "certify", "understand"]):
                await chk.check()
                filled[chk_lbl[:50] or "Consent Checkbox"] = "checked"
        except Exception:
            pass

    # Radio button groups (Yes/No and other single-choice questions rendered
    # as radio inputs rather than <select>/combobox). Previously these were
    # only ever filled during a self-healing retry *after* a failure was
    # already detected — never on the first pass — which is why required
    # Yes/No questions like "willing to relocate?" consistently landed empty
    # at DOM-verification time even though an answer had already been
    # resolved and marked verified.
    radio_elements = await page.locator('input[type="radio"]:visible').all()
    seen_radio_names: set[str] = set()
    for radio in radio_elements:
        name = ""
        try:
            name = await radio.get_attribute("name") or ""
            if not name or name in seen_radio_names:
                continue
            seen_radio_names.add(name)

            group = page.locator(f'input[type="radio"][name="{name}"]')
            group_count = await group.count()
            if group_count == 0:
                continue

            options: list[str] = []
            option_ids: list[str] = []
            for idx in range(group_count):
                opt = group.nth(idx)
                opt_id = await opt.get_attribute("id") or ""
                opt_label = (await opt.get_attribute("value") or "").strip()
                if opt_id:
                    lbl_el = page.locator(f'label[for="{opt_id}"]').first
                    if await lbl_el.count() > 0:
                        text = (await lbl_el.inner_text()).strip()
                        if text:
                            opt_label = text
                if opt_label:
                    options.append(opt_label)
                    option_ids.append(opt_id)

            if not options or not option_ids:
                continue

            # Group label: fieldset/legend first, else the nearest ancestor
            # field container's leading text (mirrors the checkbox lookup above).
            group_lbl = ""
            first_radio_id = option_ids[0]
            if first_radio_id:
                fieldset = page.locator(f'fieldset:has(#{first_radio_id})').first
                if await fieldset.count() > 0:
                    legend = fieldset.locator("legend").first
                    if await legend.count() > 0:
                        group_lbl = (await legend.inner_text()).strip()
            if not group_lbl:
                parent = radio.locator(
                    'xpath=ancestor::div[contains(@class, "field") or contains(@class, "form-group") or contains(@class, "custom-question")][1]'
                ).first
                if await parent.count() > 0:
                    full_text = (await parent.inner_text()).strip()
                    group_lbl = full_text.split("\n")[0].strip() if full_text else ""
            if not group_lbl:
                continue

            resolution = resolve_answer(question_text=group_lbl, profile=profile, options=options, answer_lib=answer_lib)
            if not resolution.answer or resolution.blocking_errors:
                continue

            if await _select_radio_option(page, first_radio_id, resolution.answer):
                filled[group_lbl[:50]] = resolution.answer
        except Exception as exc:
            logger.debug("Radio group fill error on name=%s: %s", name or "?", exc)
            continue

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

    # 4. Standard & Custom Text Inputs (LinkedIn, Company, Title, Website, Portfolio)
    text_inputs = await page.locator('input[type="text"], input[type="url"], input[type="search"], input:not([type])').all()
    for inp in text_inputs:
        try:
            if not await inp.is_visible():
                continue
            role = await inp.get_attribute("role") or ""
            if role == "combobox":
                continue
            curr_val = (await inp.input_value()).strip()
            if curr_val:
                continue

            inp_id = await inp.get_attribute("id") or ""
            inp_lbl = ""
            if inp_id:
                lbl_el = page.locator(f'label[for="{inp_id}"]').first
                if await lbl_el.count() > 0:
                    inp_lbl = (await lbl_el.inner_text()).strip()
            if not inp_lbl:
                parent = inp.locator('xpath=ancestor::div[contains(@class, "field") or contains(@class, "form-group") or contains(@class, "custom-question")][1]').first
                if await parent.count() > 0:
                    inp_lbl = (await parent.inner_text()).strip()

            inp_lbl_lower = inp_lbl.lower()
            if not inp_lbl_lower:
                continue

            val_to_fill = ""
            if "linkedin" in inp_lbl_lower:
                val_to_fill = profile.get("linkedin") or "https://www.linkedin.com/in/amsborse/"
                filled["LinkedIn"] = val_to_fill
            elif "current company" in inp_lbl_lower or "most recent company" in inp_lbl_lower or "your current company" in inp_lbl_lower or "employer" in inp_lbl_lower:
                val_to_fill = profile.get("currentCompany") or "Microsoft"
                filled["Current Company"] = val_to_fill
            elif "current title" in inp_lbl_lower or "most recent title" in inp_lbl_lower or "your current title" in inp_lbl_lower or "job title" in inp_lbl_lower:
                val_to_fill = profile.get("currentTitle") or "Senior Software Engineer"
                filled["Current Title"] = val_to_fill
            elif "state in which you" in inp_lbl_lower or "state of residence" in inp_lbl_lower:
                val_to_fill = profile.get("state") or "Washington"
                filled["State"] = val_to_fill
            elif "github" in inp_lbl_lower:
                val_to_fill = profile.get("github") or "https://github.com/amsborse"
                filled["GitHub"] = val_to_fill
            elif "portfolio" in inp_lbl_lower or "website" in inp_lbl_lower:
                val_to_fill = profile.get("portfolio") or profile.get("website") or "https://amsborse.github.io/resume"
                filled["Website"] = val_to_fill

            if val_to_fill:
                await inp.fill(val_to_fill)
                await asyncio.sleep(0.1)
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
    """Run the submission on the dedicated Proactor-loop thread (see browser_runner._ensure_playwright_loop).

    Playwright's browser launch spawns a subprocess via asyncio, which raises a bare
    NotImplementedError on Windows if it runs on the ambient (non-Proactor) event loop —
    e.g. uvicorn's own request-handling loop. Routing through browser_runner's dedicated
    Proactor thread avoids that, matching the workaround already used elsewhere for
    manual (non-autopilot) applications.
    """
    try:
        # Check if already running on a valid event loop with Playwright capability
        return await _execute_live_playwright_submission_impl(
            job_item=job_item,
            profile=profile,
            answer_lib=answer_lib,
            headless=headless,
            timeout_sec=timeout_sec,
            log_callback=log_callback,
        )
    except NotImplementedError:
        # On Windows non-Proactor loops (e.g. standard thread), route via dedicated Proactor loop
        from app.services.application_assistant.browser_runner import run_playwright_async
        return await run_playwright_async(
            _execute_live_playwright_submission_impl(
                job_item=job_item,
                profile=profile,
                answer_lib=answer_lib,
                headless=headless,
                timeout_sec=timeout_sec,
                log_callback=log_callback,
            ),
            timeout=timeout_sec + 30,
        )


async def _execute_live_playwright_submission_impl(
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

    # Per-application Gmail plus-addressing (deterministic reply tracking) —
    # read-only lookup; falls back to the real profile email on any failure
    # or if the draft predates this field, never blocks submission.
    try:
        from app.db.store import session_scope
        from app.services.application_assistant.persistence import application_id_for_job, get_application_draft

        with session_scope() as _tracking_db:
            _draft = get_application_draft(_tracking_db, application_id_for_job(job_id))
        _tracking_email = (_draft or {}).get("trackingEmail")
    except Exception:
        _tracking_email = None
    if _tracking_email:
        profile = {**profile, "email": _tracking_email}

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
            page_title_lower = (await page.title()).lower()
            url_says_expired = ("/open-roles" in current_url_lower or "/careers/search" in current_url_lower or "/jobs/search" in current_url_lower) and not any(term in current_url_lower for term in ["/jobs/", "gh_jid="]) or ("404" in page_title_lower or "not found" in page_title_lower)

            # Some ATS pages (e.g. Greenhouse) keep the original job URL but render an inline
            # banner saying the posting closed, instead of redirecting — catch that by text too.
            EXPIRED_TEXT_PATTERNS = (
                "is no longer open",
                "no longer accepting applications",
                "no longer active",
                "position has been filled",
                "posting has expired",
                "this job is closed",
                "page not found",
            )
            page_text_lower = ""
            if not url_says_expired:
                try:
                    page_text_lower = (await page.locator("body").inner_text(timeout=3000)).lower()
                except Exception:
                    page_text_lower = ""
            text_says_expired = any(p in page_text_lower for p in EXPIRED_TEXT_PATTERNS)

            if url_says_expired or text_says_expired:
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

            # If application form is not yet visible, check for matching job links or "Apply" buttons
            try:
                form_present = await target_frame.locator('input[name*="name" i], #first_name, #email, form').count() > 0
                if not form_present:
                    # Check for direct link to specific job if gh_jid was in the URL
                    if "gh_jid=" in app_url:
                        import urllib.parse
                        parsed = urllib.parse.urlparse(app_url)
                        qs = urllib.parse.parse_qs(parsed.query)
                        jid = qs.get("gh_jid", [""])[0]
                        if jid:
                            matching_link = page.locator(f'a[href*="{jid}"], a[href*="gh_jid={jid}"], a[href*="job-detail?gh_jid={jid}"]').first
                            if await matching_link.count() > 0 and await matching_link.is_visible():
                                logger.info("Navigating to specific job link for gh_jid=%s...", jid)
                                if log_callback:
                                    log_callback(f"Opening specific job posting for gh_jid={jid}...")
                                await matching_link.click()
                                await asyncio.sleep(3.0)
                                for frame in page.frames:
                                    if frame != page and any(term in frame.url for term in ["greenhouse.io", "lever.co", "ashby"]):
                                        target_frame = frame
                                        break

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
                            for frame in page.frames:
                                if frame != page and any(term in frame.url for term in ["greenhouse.io", "lever.co", "ashby"]):
                                    target_frame = frame
                                    break
                            break
            except Exception as nav_err:
                logger.debug("Initial form exposure navigation warning: %s", nav_err)

            # ─── DISCOVER & PERSIST FIELDS BEFORE RESOLUTION ─────────────────
            try:
                discovered_dom_fields, _ = await _extract_dom_form_state(target_frame)
                if discovered_dom_fields:
                    persist_discovered_form(
                        application_id=str(job_id),
                        job_id=str(job_id),
                        ats="greenhouse" if "greenhouse" in app_url.lower() else "ats",
                        fields=discovered_dom_fields,
                        page_url=page.url,
                    )
            except Exception as disc_err:
                logger.debug("Field discovery persistence error: %s", disc_err)

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

                    # ── Use centralized resolver instead of if/elif heuristics ──
                    if not fix_val:
                        heal_resolution = resolve_answer(
                            question_text=f_label,
                            profile=profile,
                            answer_lib=answer_lib,
                        )
                        fix_val = heal_resolution.answer
                    if f_id:
                        elem = target_frame.locator(f'[id="{f_id}"]').first
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
                                    if fix_val and str(fix_val).lower() not in ("none", "null", "undefined", ""):
                                        await _select_react_combobox(target_frame, f_id, str(fix_val))
                                        filled_fields[f_label or f_id] = str(fix_val)
                                        if log_callback:
                                            log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                                elif el_type == "radio":
                                    if fix_val and str(fix_val).lower() not in ("none", "null", "undefined", "") and await _select_radio_option(target_frame, f_id, str(fix_val)):
                                        filled_fields[f_label or f_id] = str(fix_val)
                                        if log_callback:
                                            log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                                elif el_type == "checkbox":
                                    if fix_val and str(fix_val).lower() not in ("no", "false", "0", "unchecked", "none", "null"):
                                        await elem.check()
                                        filled_fields[f_label or f_id] = "checked"
                                        if log_callback:
                                            log_callback(f"Self-healed checkbox [{f_label or f_id}] -> checked")
                                elif el_type in ("select-one", "select-multiple"):
                                    # Native <select> elements don't support .fill() — Playwright raises on
                                    # them, which the broad except below was silently swallowing, leaving
                                    # the field empty despite a resolved fix_val (e.g. Country, Yes/No drops).
                                    if fix_val and str(fix_val).lower() not in ("none", "null", "undefined", ""):
                                        opt_texts = await elem.locator("option").all_inner_texts()
                                        wanted = str(fix_val).strip().lower()
                                        matched_opt = None
                                        for opt_t in opt_texts:
                                            clean = opt_t.strip()
                                            if not clean or clean.lower() in ("select...", "select", "--", "choose"):
                                                continue
                                            if wanted == clean.lower() or wanted in clean.lower() or clean.lower() in wanted:
                                                matched_opt = clean
                                                break
                                        if matched_opt:
                                            await elem.select_option(label=matched_opt)
                                            filled_fields[f_label or f_id] = matched_opt
                                            if log_callback:
                                                log_callback(f"Self-healed [{f_label or f_id}] -> '{matched_opt}'")
                                        elif log_callback:
                                            log_callback(f"Self-heal: no matching option for [{f_label or f_id}] wanting '{fix_val}'", lvl="warning")
                                else:
                                    # Never coerce an unknown field to the literal string "None"
                                    if fix_val and str(fix_val).lower() not in ("none", "null", "undefined", ""):
                                        await elem.fill(str(fix_val))
                                        filled_fields[f_label or f_id] = str(fix_val)
                                        if log_callback:
                                            log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                            except Exception as fill_err:
                                logger.warning("Fill error on %s: %s", f_id, fill_err)



                await asyncio.sleep(0.5)

            # ─── VERIFIED AUTONOMY SUBMISSION POLICY GATE ─────────────────────
            # 1. Collect all answer resolutions from form filling
            form_resolutions: list[AnswerResolution] = []
            for lbl, ans in filled_fields.items():
                form_resolutions.append(
                    resolve_answer(question_text=lbl, profile=profile, answer_lib=answer_lib)
                )

            # 2. Run cross-field deterministic validation
            cross_field_report = validate_answers(form_resolutions, profile)

            # 3. Read back live browser DOM state
            dom_verification = await verify_browser_dom_state(target_frame, form_resolutions, profile)

            # 4. Evaluate centralized SubmissionPolicy
            policy_result = SubmissionPolicy.evaluate(
                resolutions=form_resolutions,
                validation_report=cross_field_report,
                dom_verification=dom_verification,
                profile=profile,
            )

            # 5. Persist pre-submit audit report
            persist_pre_submit_report(
                application_id=str(job_id),
                report=cross_field_report,
                resolutions=form_resolutions,
            )

            # 6. Policy Check: If not READY_TO_SUBMIT, stage for review (never force submit)
            if not policy_result.can_auto_submit:
                reasons_str = "; ".join(policy_result.reasons)
                logger.warning("Verified Autonomy Policy Decision: NEEDS_REVIEW. Reason(s): %s", reasons_str)
                if log_callback:
                    log_callback(f"Submission Staged for Review: {policy_result.reasons[0] if policy_result.reasons else 'Ambiguity detected'}", lvl="warning")

                pre_screenshot_path = SCREENSHOTS_DIR / f"{job_id}_needs_review.png"
                try:
                    await page.screenshot(path=str(pre_screenshot_path), full_page=True)
                except Exception:
                    pass

                return {
                    "submitted": False,
                    "stagedForReview": True,
                    "status": "NEEDS_REVIEW",
                    "error": reasons_str,
                    "evidence": {
                        "policyEvaluation": policy_result.to_dict(),
                        "domVerification": dom_verification.to_dict(),
                        "preScreenshotPath": str(pre_screenshot_path.resolve()) if pre_screenshot_path.exists() else "",
                    },
                    "fieldsFilled": filled_fields,
                }

            logger.info("Verified Autonomy Policy Decision: READY_TO_SUBMIT (All gates passed)")
            if log_callback:
                log_callback("Verified Autonomy: 100% verified against profile and live DOM. Submitting...")

            # Pre-submit screenshot
            pre_screenshot_path = SCREENSHOTS_DIR / f"{job_id}_presubmit.png"
            try:
                await page.screenshot(path=str(pre_screenshot_path), full_page=True)
            except Exception:
                pass

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
            await asyncio.sleep(4.0)

            # ─── GREENHOUSE EMAIL VERIFICATION FLOW ─────────────────────────────
            from app.services.application_assistant.greenhouse_verification_service import handle_greenhouse_verification_flow
            candidate_email = derive_contact_email(profile.get("email") or "") or "amsborse+career@gmail.com"
            try:
                verification_handled = await handle_greenhouse_verification_flow(
                    page=page,
                    target_frame=target_frame,
                    company=company,
                    candidate_email=candidate_email,
                    timeout_sec=45.0,
                    log_callback=log_callback,
                )
                if verification_handled:
                    logger.info("Greenhouse verification flow executed successfully.")
            except Exception as v_ex:
                logger.warning("Greenhouse verification flow check encountered: %s", v_ex)

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
                tailoring_mode=job_item.get("tailoringMode"),
                resume_file_used=job_item.get("resumeFileUsed"),
                match_score_at_submission=job_item.get("matchScoreAtSubmission"),
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
            # exc_info=True so a bare exception (e.g. NotImplementedError with no
            # message) still leaves a full traceback in the logs instead of just
            # an unhelpful empty string.
            logger.error("Playwright submission failed: %s", e, exc_info=True)
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
