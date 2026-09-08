"""Playwright Autopilot Live Submitter with Strict Pre-Submit & Post-Submit Verification."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.db.store import now_iso

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


_UPLOAD_STAGING_DIR = Path(__file__).resolve().parents[3] / "data" / "application_assistant" / "resume_uploads"


def get_resume_upload_payload(profile: dict[str, Any]) -> str:
    """Resolve the file path to hand to Playwright's set_input_files().

    A tailored resume is stored on disk under a job-id-keyed filename (so
    concurrent jobs never collide and the file used for a given submission
    stays traceable), but that internal filename must never be what actually
    reaches the employer — set_input_files uploads a file under its own
    on-disk basename, so a name like "apjob_<uuid>_aggressive.pdf" would be
    exactly what the ATS sees, reading as obviously machine-generated. Stage
    a copy under the candidate's normal resume filename, in a job-id-keyed
    subfolder so concurrent workers still never collide, and upload that
    instead — the original tailored file on disk keeps its traceable name.
    """
    resolved = get_active_resume_path(profile)
    if not resolved:
        return ""
    resolved_path = Path(resolved)
    display_name = PRIMARY_RESUME_PATH.name  # "Akshay_Borse_Resume.pdf"
    if resolved_path.name == display_name:
        return resolved
    try:
        job_dir = _UPLOAD_STAGING_DIR / resolved_path.stem
        job_dir.mkdir(parents=True, exist_ok=True)
        staged_path = job_dir / display_name
        staged_path.write_bytes(resolved_path.read_bytes())
        return str(staged_path.resolve())
    except OSError:
        return resolved


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
        var seenRadioNames = {};
        for (var i = 0; i < elements.length; i++) {
            var el = elements[i];
            var id = el.id || '';
            var name = el.name || el.getAttribute('name') || '';
            var ariaLabel = el.getAttribute('aria-label') || '';
            var isCombobox = el.getAttribute('role') === 'combobox';
            var inputType = (el.type || '').toLowerCase();

            if (id.indexOf('recaptcha') !== -1 || name.indexOf('recaptcha') !== -1 || el.className.indexOf('g-recaptcha-response') !== -1) {
                continue;
            }

            // A radio *group* is one question — querySelectorAll returns every
            // individual <input> in it, so without dedup the same question
            // shows up once per option, each independently guessing its own
            // label via the (fragile) per-element fallback below. Two inputs
            // in the same group can land on different, wrong ancestor divs and
            // report different labels for what is really one question — one of
            // which can end up matching a *different* field's resolved answer
            // during verification (observed live: a location answer flagged as
            // conflicting with an unrelated Yes/No radio's selected value).
            // Emit exactly one entry per group, labeled via fieldset/legend
            // first — the same reliable signal the fill-side logic already
            // prefers for these groups — before falling back to nearby text.
            if (inputType === 'radio' && name) {
                if (seenRadioNames[name]) continue;
                seenRadioNames[name] = true;
            }

            var label = '';
            if (inputType === 'radio' && id) {
                try {
                    var fs = document.querySelector('fieldset:has(#' + CSS.escape(id) + ')');
                    if (fs) {
                        var lg = fs.querySelector('legend');
                        if (lg) label = lg.innerText;
                    }
                } catch(err) {}
            }
            if (!label && id) {
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
            best_text = ""

            fallback_opt = None
            fallback_text = ""
            for i in range(opt_count):
                opt = options_loc.nth(i)
                if not await opt.is_visible():
                    continue
                opt_text = (await opt.inner_text()).strip()
                opt_text_lower = opt_text.lower()
                if not opt_text or opt_text_lower in ("select...", "select", "--", "choose"):
                    continue

                if clean_search and opt_text_lower == clean_search:
                    best_opt = opt
                    best_text = opt_text
                    break

                # "male" is literally a substring of "female", so containment
                # alone can match the wrong option — only accept it as a
                # fallback, and never let it beat an exact match found later.
                is_gender_collision = (
                    (clean_search == "male" and "female" in opt_text_lower)
                    or (clean_search == "female" and opt_text_lower == "male")
                )
                if clean_search and not is_gender_collision and fallback_opt is None and (clean_search in opt_text_lower or opt_text_lower in clean_search):
                    fallback_opt = opt
                    fallback_text = opt_text

            if best_opt is None and fallback_opt is not None:
                best_opt = fallback_opt
                best_text = fallback_text

            # Only click a real match. Falling back to "whichever option is
            # first" when nothing matches search_text isn't a fallback, it's a
            # fabricated answer — observed live: a bad search term ("Auburn")
            # against a Yes/No dropdown blindly clicked "Yes" (the first
            # option), then the caller recorded the *original* search term as
            # the intended answer, guaranteeing a nonsensical mismatch against
            # the real DOM value at verification time. Leaving the field
            # untouched here means it correctly stays flagged for review.
            if best_opt:
                await best_opt.click(force=True)
                await asyncio.sleep(0.2)
                return best_text
            await page.keyboard.press("Escape")
            return ""

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
            if wanted and any(wanted == candidate for candidate in candidates if candidate):
                await radio.check(force=True)
                return True
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
            for candidate in candidates:
                if not candidate:
                    continue
                is_gender_collision = (
                    (wanted == "male" and "female" in candidate)
                    or (wanted == "female" and candidate == "male")
                )
                if is_gender_collision:
                    continue
                if wanted and (wanted in candidate or candidate in wanted):
                    await radio.check()
                    return True
    except Exception as exc:
        logger.debug("Radio selection error for %s: %s", field_id, exc)
    return False


# Categories the candidate should never volunteer into an OPTIONAL field.
# Per an explicit standing instruction: CareerOS fills a field only when the
# application actually requires it. These are all legally-voluntary or
# negotiation-sensitive disclosures — demographics, pay, academic scores — and
# offering them unprompted just hands the employer extra grounds to screen on.
# A REQUIRED field of the same type is still answered normally; the rule is
# about volunteering, not about refusing to answer.
VOLUNTEER_ONLY_TYPES = frozenset({
    QuestionType.GENDER,
    QuestionType.PRONOUNS,
    QuestionType.TRANSGENDER,
    QuestionType.SEXUAL_ORIENTATION,
    QuestionType.ETHNICITY_HISPANIC_LATINO,
    QuestionType.RACE,
    QuestionType.VETERAN_STATUS,
    QuestionType.DISABILITY,
    QuestionType.FIRST_GEN_PROFESSIONAL,
    QuestionType.SALARY,
    QuestionType.GPA,
    QuestionType.TEST_SCORE,
})


async def _fill_all_greenhouse_comboboxes(
    page: Any,
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Fill all Greenhouse dropdowns & React Select controls using the centralized resolver.

    Returns (filled, filled_ids): filled_ids maps the same label keys to the
    live DOM element id so callers can rebuild an AnswerResolution with
    field_id set — without it, DOM verification has to pair an answer back to
    its element by fuzzy label matching, which can pair the wrong two fields.
    """
    filled: dict[str, str] = {}
    filled_ids: dict[str, str] = {}
    all_resolutions: list[AnswerResolution] = []

    # Snapshot ids up front rather than holding Locator.all()'s positional
    # (nth-indexed) references: clicking an earlier combobox's autocomplete
    # suggestion can insert/remove sibling DOM nodes, which reflows those
    # positional locators onto a *different* physical element for later
    # iterations — observed as e.g. the Location field's resolved answer
    # ("Auburn, WA") getting compared against a completely unrelated Yes/No
    # combobox's live DOM value during verification. Re-locating by id each
    # iteration keeps every action bound to the same physical element
    # regardless of what happens to its siblings in between.
    cb_ids: list[str] = await page.eval_on_selector_all(
        'input[role="combobox"]', "els => els.map(e => e.id)"
    )

    for cid in cb_ids:
        try:
            if not cid or cid == "iti-0__search-input":
                continue

            el = page.locator(f'[id="{cid}"]').first
            if await el.count() == 0:
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

            # Skip optional demographic/pay/academic dropdowns entirely.
            # Greenhouse marks required fields with a "*" in the label and/or
            # aria-required on the input; anything without either is genuinely
            # optional, so a voluntary disclosure there stays blank.
            is_required = "*" in lbl_text or bool(await el.evaluate(
                "el => el.required || el.getAttribute('aria-required') === 'true'"
            ))
            if not is_required and classify_question(lbl_text, cid, None) in VOLUNTEER_ONLY_TYPES:
                logger.info("Skipping optional voluntary field '%s' (not required)", lbl_text[:60])
                continue

            # Locate surrounding React-Select container or the input itself
            wrapper = page.locator(f'div.select__control:has([id="{cid}"]), div[class*="control"]:has([id="{cid}"])').first
            target_to_open = wrapper if await wrapper.count() > 0 else el

            # Some Greenhouse comboboxes (observed live on the EEOC Gender
            # field) arrive with a real value already pre-selected before any
            # autofill runs, rather than starting blank. Capture that closed-
            # state value now, before we open the menu — if the resolved
            # answer later turns out to already match it, we skip touching
            # the control entirely rather than opening/clicking it and
            # risking an unnecessary re-selection landing on the wrong option.
            preexisting_value = (await el.evaluate("""el => {
                var wrapper = el.closest('div.select__control, div[class*="select__control"]');
                if (!wrapper) return '';
                var sv = wrapper.querySelector('[class*="singleValue"], [class*="single-value"]');
                return sv ? sv.textContent.trim() : '';
            }""") or "").strip()

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

            if len(available_options) == 1:
                # A field with exactly one real option (e.g. a GDPR/data-
                # processing "Acknowledge/Confirm" disclosure) isn't a
                # judgment call — there's nothing to classify or guess,
                # since selecting it is the only possible action. Requiring
                # resolve_answer to recognize the question type first was
                # leaving these permanently blank and staged for review even
                # though no real ambiguity exists.
                resolution = AnswerResolution(
                    field_id=cid,
                    question=lbl_text,
                    question_type="SINGLE_OPTION",
                    answer=available_options[0],
                    resolution_method="SINGLE_OPTION_FORCED",
                    confidence=1.0,
                )
                all_resolutions.append(resolution)
            else:
                # ── Check if this is a phone country-CODE dropdown, not a plain country-NAME field ──
                # A plain "Country" (of residence) dropdown also has 100+
                # options and trivially contains "united states" as one of
                # them — that old check misclassified genuine country
                # fields as the phone dial-code field, resolving them to
                # "United States +1" instead of "United States", which then
                # can't be selected in a country-name-only dropdown and
                # leaves it permanently invalid. A real dial-code list is
                # distinguished by most options ending in "+<digits>".
                dial_code_count = sum(1 for o in available_options if re.search(r"\+\d{1,4}$", o.strip()))
                is_country_code = len(available_options) > 100 and dial_code_count > len(available_options) * 0.5
                effective_q_text = "Country Code" if is_country_code else lbl_text

                # ── Centralized resolution (replaces all if/elif heuristics) ──
                # field_id=cid lets DOM verification match this resolution back to
                # its exact DOM element by id instead of by label-text comparison
                # against a separately-computed label from DOM-state extraction —
                # two independent label lookups that don't always agree on wording,
                # which otherwise falls back to substring matching and can pair a
                # resolution with a different field's selected value entirely.
                resolution = resolve_answer(
                    question_text=effective_q_text,
                    profile=profile,
                    options=available_options,
                    answer_lib=answer_lib,
                    field_id=cid,
                )
                all_resolutions.append(resolution)

            target_text = resolution.answer
            if not target_text:
                logger.info("Combobox '%s' unresolved (type=%s), skipping", lbl_text[:50], resolution.question_type)
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.05)
                continue

            if preexisting_value and preexisting_value.lower() == target_text.strip().lower():
                filled[lbl_text[:50]] = preexisting_value
                filled_ids[lbl_text[:50]] = cid
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

            # 1. Exact or partial match click via fast locator. Exact matches
            # are checked across every option before any substring fallback —
            # Playwright's `has_text` filter does case-insensitive substring
            # matching, so a naive `.filter(has_text="Male")` also matches the
            # "Female" option (since "female" literally contains "male"), and
            # `.first` silently clicks whichever comes first in DOM order.
            # Anchoring the regex to the full option text prevents that.
            candidate_str = None
            for opt_str in available_options:
                if target_lower == opt_str.strip().lower():
                    candidate_str = opt_str
                    break
            if candidate_str is None:
                for opt_str in available_options:
                    opt_lower = opt_str.strip().lower()
                    is_gender_collision = (
                        (target_lower == "male" and "female" in opt_lower)
                        or (target_lower == "female" and opt_lower == "male")
                    )
                    if is_gender_collision:
                        continue
                    if target_lower in opt_lower or opt_lower in target_lower:
                        candidate_str = opt_str
                        break
            if candidate_str is not None:
                exact_pattern = re.compile(rf"^\s*{re.escape(candidate_str.strip())}\s*$", re.IGNORECASE)
                opt_to_click = page.locator('.select__option, [role="option"]').filter(has_text=exact_pattern).first
                if await opt_to_click.count() > 0:
                    await opt_to_click.click(force=True)
                    filled[lbl_text[:50]] = candidate_str
                    filled_ids[lbl_text[:50]] = cid
                    matched = True
                    await asyncio.sleep(0.1)

            # 2. Dynamic typing pass for searchable/async comboboxes (e.g. School, Major)
            if not matched and target_text:
                try:
                    await el.click(force=True)
                    await page.keyboard.type(target_text, delay=20)
                    await asyncio.sleep(0.3)

                    visible_opts = page.locator('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option')
                    opt_count = await visible_opts.count()
                    chosen = None
                    fallback = None
                    for oi in range(min(opt_count, 20)):
                        cand = visible_opts.nth(oi)
                        if not await cand.is_visible():
                            continue
                        c_txt = (await cand.inner_text()).strip()
                        c_txt_lower = c_txt.lower()
                        if not c_txt or c_txt_lower in ("no options", "select..."):
                            continue
                        is_gender_collision = (
                            (target_lower == "male" and "female" in c_txt_lower)
                            or (target_lower == "female" and c_txt_lower == "male")
                        )
                        if is_gender_collision:
                            continue
                        if fallback is None:
                            fallback = (cand, c_txt)
                        if c_txt_lower == target_lower:
                            chosen = (cand, c_txt)
                            break
                    pick = chosen or fallback
                    if pick:
                        await pick[0].click(force=True)
                        filled[lbl_text[:50]] = pick[1]
                        filled_ids[lbl_text[:50]] = cid
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

    return filled, filled_ids


async def _fill_standard_and_react_fields(
    page: Any,
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None,
    company: str,
    title: str,
    resume_file: str,
    log_cb: Any = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Execute primary field filling across standard inputs and React comboboxes.

    Returns (filled, filled_ids) — see _fill_all_greenhouse_comboboxes for why
    filled_ids (label -> live DOM element id) matters for verification.
    """
    filled: dict[str, str] = {}
    filled_ids: dict[str, str] = {}

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
            filled_ids["Location"] = await loc_input.get_attribute("id") or ""
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
            # Playwright already emits input/change. React may remove this
            # input once attached; dispatching again waits on a vanished node.
            filled["Resume"] = os.path.basename(resume_file)
            if log_cb:
                log_cb(f"Attached resume ({os.path.basename(resume_file)})")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("Resume attach error: %s", e)

    # 3. React Comboboxes & Native Selects
    if log_cb:
        log_cb("Resolving dropdowns & comboboxes (EEOC / Custom)...")
    cb_filled, cb_ids = await _fill_all_greenhouse_comboboxes(page, profile, answer_lib)
    filled.update(cb_filled)
    filled_ids.update(cb_ids)

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

            if len(available) == 1:
                # Same rationale as the combobox path above: one real option
                # means there's no ambiguity to classify, just select it.
                await sel_el.select_option(label=available[0])
                filled[sel_lbl[:50]] = available[0]
                filled_ids[sel_lbl[:50]] = sel_id
                continue

            resolution = resolve_answer(
                question_text=sel_lbl,
                profile=profile,
                options=available,
                answer_lib=answer_lib,
                field_id=sel_id,
            )
            if resolution.answer and not resolution.blocking_errors:
                target_lower = resolution.answer.strip().lower()
                # Exact match first: substring containment alone is unsafe for
                # short answers like "Male", which is literally a substring of
                # "Female" ("fe-male") — checking containment before equality
                # let a "Male" intent select the "Female" option whenever
                # Female happened to come first in the dropdown's option order.
                chosen_opt = None
                for opt_t in available:
                    if opt_t.strip().lower() == target_lower:
                        chosen_opt = opt_t
                        break
                if chosen_opt is None:
                    for opt_t in available:
                        opt_lower = opt_t.strip().lower()
                        is_gender_collision = (
                            (target_lower == "male" and "female" in opt_lower)
                            or (target_lower == "female" and opt_lower == "male")
                        )
                        if is_gender_collision:
                            continue
                        if target_lower in opt_lower or opt_lower in target_lower:
                            chosen_opt = opt_t
                            break
                if chosen_opt:
                    await sel_el.select_option(label=chosen_opt)
                    filled[sel_lbl[:50]] = chosen_opt
                    filled_ids[sel_lbl[:50]] = sel_id
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
                await chk.check(force=True)
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
                # Last resort: some Greenhouse demographic questions render
                # without any field/form-group wrapper class, only a bare
                # ancestor <div>/<fieldset> — without a label these groups
                # were silently skipped forever (never even attempted),
                # showing up at DOM-verification time as "an unlabeled
                # field" left empty. Walk up to the nearest container that
                # actually has text distinct from the option labels
                # themselves, rather than giving up immediately.
                broad_parent = radio.locator("xpath=ancestor::fieldset[1] | ancestor::div[2]").first
                if await broad_parent.count() > 0:
                    full_text = (await broad_parent.inner_text()).strip()
                    first_line = full_text.split("\n")[0].strip() if full_text else ""
                    if first_line and first_line.lower() not in [o.lower() for o in options]:
                        group_lbl = first_line
            if not group_lbl:
                continue

            resolution = resolve_answer(question_text=group_lbl, profile=profile, options=options, answer_lib=answer_lib, field_id=first_radio_id)
            if not resolution.answer or resolution.blocking_errors:
                continue

            if await _select_radio_option(page, first_radio_id, resolution.answer):
                filled[group_lbl[:50]] = resolution.answer
                filled_ids[group_lbl[:50]] = first_radio_id
        except Exception as exc:
            logger.debug("Radio group fill error on name=%s: %s", name or "?", exc)
            continue

    # Checkbox-styled single-choice groups: some Greenhouse custom questions
    # (observed live: "If not located in the greater Seattle area, are you
    # willing to relocate?" -> Yes/No/Not Applicable) render as a <fieldset>
    # of individually-named checkboxes (name="question_X[]") rather than a
    # radio group or combobox. The existing checkbox loop above only ever
    # checks boxes whose own label mentions "consent"/"agree"/etc., so a
    # Yes/No/Not-Applicable-as-checkboxes question was silently skipped
    # every time — this handles fieldset-grouped checkboxes as their own
    # single-choice question, resolved the same way as a radio group.
    checkbox_group_fieldsets = await page.locator('fieldset:has(input[type="checkbox"])').all()
    for fieldset in checkbox_group_fieldsets:
        try:
            legend = fieldset.locator("legend").first
            if await legend.count() == 0:
                continue
            group_lbl = (await legend.inner_text()).strip()
            if not group_lbl:
                continue

            boxes = fieldset.locator('input[type="checkbox"]')
            box_count = await boxes.count()
            if box_count < 2:
                # A single checkbox under a fieldset is the plain consent
                # case the loop above already owns — not a choice group.
                continue

            options: list[str] = []
            option_ids: list[str] = []
            already_checked = False
            for idx in range(box_count):
                box = boxes.nth(idx)
                if await box.is_checked():
                    already_checked = True
                    break
                box_id = await box.get_attribute("id") or ""
                opt_label = ""
                if box_id:
                    lbl_el = page.locator(f'label[for="{box_id}"]').first
                    if await lbl_el.count() > 0:
                        opt_label = (await lbl_el.inner_text()).strip()
                if opt_label:
                    options.append(opt_label)
                    option_ids.append(box_id)
            if already_checked or not options:
                continue

            resolution = resolve_answer(question_text=group_lbl, profile=profile, options=options, answer_lib=answer_lib, field_id=option_ids[0])
            if not resolution.answer or resolution.blocking_errors:
                continue

            target_lower = resolution.answer.strip().lower()
            chosen_id = None
            for opt_str, opt_id in zip(options, option_ids):
                if opt_str.strip().lower() == target_lower:
                    chosen_id = opt_id
                    break
            if chosen_id is None:
                for opt_str, opt_id in zip(options, option_ids):
                    opt_lower = opt_str.strip().lower()
                    if target_lower in opt_lower or opt_lower in target_lower:
                        chosen_id = opt_id
                        break
            if chosen_id:
                # Neither clicking the raw <input> nor its <label> reliably
                # flips these custom-styled checkboxes (confirmed live:
                # Playwright reports each click completed but .checked never
                # changes) — this is a React-controlled input that needs its
                # real DOM property set plus native input/change/click events
                # dispatched for React's synthetic event system to notice.
                target_box = page.locator(f'[id="{chosen_id}"]').first
                await target_box.evaluate("""el => {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked').set;
                    setter.call(el, true);
                    el.dispatchEvent(new Event('click', { bubbles: true }));
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""")
                if not await target_box.is_checked():
                    label_loc = page.locator(f'label[for="{chosen_id}"]').first
                    if await label_loc.count() > 0:
                        await label_loc.click(force=True)
                    else:
                        await target_box.check(force=True)
                filled[group_lbl[:50]] = resolution.answer
                filled_ids[group_lbl[:50]] = chosen_id
        except Exception as exc:
            logger.debug("Checkbox group fill error: %s", exc)
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
            # Store the full answer, not a truncated preview — this dict feeds
            # DOM verification later (via form_resolutions), which compares it
            # against the live textarea's full value. A truncated "...' stored
            # here always mismatches the real value, staging every essay-style
            # answer for review even when it was filled correctly.
            filled[ta_lbl[:30] or "Essay"] = essay_ans
            filled_ids[ta_lbl[:30] or "Essay"] = ta_id
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
                for key in ("LinkedIn", "Current Company", "Current Title", "State", "GitHub", "Website"):
                    if filled.get(key) == val_to_fill:
                        filled_ids[key] = inp_id
                await asyncio.sleep(0.1)
        except Exception:
            pass

    return filled, filled_ids


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
    e.g. uvicorn's own request-handling loop under `--reload` (uvicorn forces
    SelectorEventLoop for its reloaded worker process, see uvicorn/loops/asyncio.py).

    This used to run the impl directly first and only fall back to the dedicated
    Proactor thread on `except NotImplementedError` — but that exception is raised
    inside Playwright's own internal driver-connection task (`Connection.run()`),
    which is scheduled fire-and-forget (`Task exception was never retrieved` in the
    logs) rather than propagated synchronously to the awaited call here. So the
    except clause never actually fires: the coroutine just hangs forever awaiting a
    driver handshake that will never arrive, since the driver subprocess never
    launched. Route through the dedicated Proactor thread unconditionally on
    Windows instead, matching the (correct) pattern in browser_runner.prepare_application.
    """
    import sys

    if sys.platform == "win32":
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

    return await _execute_live_playwright_submission_impl(
        job_item=job_item,
        profile=profile,
        answer_lib=answer_lib,
        headless=headless,
        timeout_sec=timeout_sec,
        log_callback=log_callback,
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

    # Custom-branded careers domains that embed a Greenhouse job via ?gh_jid=
    # (coupang.jobs, zoominfo.com/careers, samsara.com/company/careers, etc.)
    # render markup our submit-button/field selectors don't recognize —
    # they're built against Greenhouse's own standard form. Redirecting to
    # the canonical job-boards.greenhouse.io URL when we can confidently
    # derive one fixes "Submit button not found" on postings that are
    # genuinely live and Greenhouse-backed, not actually broken.
    if app_url and ("gh_jid=" in app_url.lower() or "greenhouse" in app_url.lower()):
        # Only attempt this when the URL itself already signals Greenhouse
        # involvement — extract_greenhouse_job_ref's job-id fallback pattern
        # (bare "/jobs/<digits>") is common to many unrelated ATS URLs too,
        # and guessing a slug from the company name for a genuinely
        # non-Greenhouse site could redirect to a wrong/nonexistent page.
        try:
            from app.services.application_assistant.providers.greenhouse import resolve_greenhouse_apply_url
            normalized_url = resolve_greenhouse_apply_url(app_url, company_name=company)
            if normalized_url and normalized_url != app_url:
                logger.info("Normalized application URL for %s: %s -> %s", company, app_url, normalized_url)
                app_url = normalized_url
        except Exception as e:
            logger.debug("Greenhouse URL normalization skipped for %s: %s", company, e)

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

    # If URL is a career hub containing gh_jid parameter, resolve to direct Greenhouse embed/job URL for 100% reliable submission
    if "gh_jid=" in app_url and not ("greenhouse.io" in app_url and "/jobs/" in app_url):
        import urllib.parse
        parsed = urllib.parse.urlparse(app_url)
        qs = urllib.parse.parse_qs(parsed.query)
        gh_jid = qs.get("gh_jid", [None])[0]
        if gh_jid:
            comp_slug = re.sub(r"[^a-zA-Z0-9]", "", company.lower())
            # Use direct embed URL so custom company career portals don't redirect or require complex nested iframe switching
            direct_board_url = f"https://job-boards.greenhouse.io/embed/job_app?for={comp_slug}&token={gh_jid}"
            logger.info("Resolved career hub gh_jid URL %s -> direct Greenhouse embed URL: %s", app_url, direct_board_url)
            app_url = direct_board_url

    # api.smartrecruiters.com/v1/... is the raw JSON REST endpoint the
    # discovery scraper sometimes captures instead of the public job page —
    # loading it in a browser shows bare JSON with no form/submit button at
    # all. jobs.smartrecruiters.com/{company}/{id} is the actual public
    # posting page and always exists for any job the API endpoint returns.
    sr_api_match = re.match(
        r"https?://api\.smartrecruiters\.com/v1/companies/([^/]+)/postings/(\d+)",
        app_url,
    )
    if sr_api_match:
        sr_company, sr_posting_id = sr_api_match.group(1), sr_api_match.group(2)
        direct_sr_url = f"https://jobs.smartrecruiters.com/{sr_company}/{sr_posting_id}"
        logger.info("Resolved SmartRecruiters API URL %s -> public posting URL: %s", app_url, direct_sr_url)
        app_url = direct_sr_url

    resume_file = get_resume_upload_payload(profile)

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # Some Greenhouse-hosted boards reset the HTTP/2 connection mid-
                # handshake, which Chromium surfaces as a hard
                # net::ERR_HTTP2_PROTOCOL_ERROR on page.goto and which retrying
                # never clears — observed deterministically on all three Roblox
                # postings, whose URLs load fine over HTTP/1.1. Forcing HTTP/1.1
                # costs a little connection reuse and makes those pages reachable.
                "--disable-http2",
            ],
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
            try:
                await asyncio.wait_for(
                    page.goto(app_url, wait_until="domcontentloaded", timeout=min(timeout_sec, 60.0) * 1000),
                    timeout=65.0,
                )
            except Exception as goto_err:
                logger.warning("Initial page.goto encountered warning (%s); checking page state...", goto_err)
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

            if target_frame == page:
                try:
                    iframe_elem = page.locator('iframe[src*="greenhouse.io"], iframe[src*="lever.co"], iframe[src*="ashby"]').first
                    if await iframe_elem.count() > 0:
                        content_fr = await iframe_elem.content_frame()
                        if content_fr:
                            target_frame = content_fr
                            if log_callback:
                                log_callback(f"Switched to application frame via element locator ({target_frame.url[:40]}...)")
                except Exception:
                    pass

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
            filled_fields, filled_field_ids = await _fill_standard_and_react_fields(
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

                dom_fields_by_id = {f.get("id"): f for f in dom_fields if f.get("id")}

                for item in missing_fields:
                    f_id = item.get("fieldId")
                    f_label = item.get("label", "")
                    f_label_lower = f_label.lower()
                    fix_val = item.get("suggestedFixValue")

                    # The LLM review returns fieldId/label pairs it read off the
                    # same dom_fields list, but it can misattribute an id to the
                    # wrong question in its own output (e.g. suggesting fieldId
                    # "candidate-location" — a different field entirely — for
                    # what it meant as the fix for a hybrid-work Yes/No
                    # question). Blindly trusting fieldId then writes the fix
                    # value into a completely unrelated field (observed live: a
                    # "Yes" fix landing in the Location autocomplete while the
                    # actual target question stayed empty). Cross-check the
                    # LLM's claimed label against that id's real DOM label
                    # before applying anything — if they share no meaningful
                    # words, the pairing is unreliable and the fix is skipped
                    # rather than corrupting the wrong field.
                    if f_id and f_id in dom_fields_by_id:
                        actual_label = dom_fields_by_id[f_id].get("label", "")
                        actual_words = {w for w in re.findall(r"[a-z]+", actual_label.lower()) if len(w) > 2}
                        claimed_words = {w for w in re.findall(r"[a-z]+", f_label_lower) if len(w) > 2}
                        if actual_words and claimed_words and not (actual_words & claimed_words):
                            logger.warning(
                                "Skipping self-heal fix: LLM label %r doesn't match actual DOM label %r for fieldId %r",
                                f_label, actual_label, f_id,
                            )
                            continue

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
                                            filled_field_ids[f_label or f_id] = f_id
                                            if log_callback:
                                                log_callback(f"Attached file for [{f_label or f_id}] ({os.path.basename(resume_file)})")
                                        except Exception as f_err:
                                            logger.warning("File attachment error on %s: %s", f_id, f_err)
                                elif is_cb:
                                    if fix_val and str(fix_val).lower() not in ("none", "null", "undefined", ""):
                                        # Record whatever _select_react_combobox actually
                                        # clicked, not the guessed fix_val — it can decline
                                        # to select anything (empty return) when fix_val
                                        # doesn't match any real option, and trusting the
                                        # guess instead of the outcome records an "intended"
                                        # answer that doesn't match what's really in the DOM.
                                        actually_selected = await _select_react_combobox(target_frame, f_id, str(fix_val))
                                        if actually_selected:
                                            filled_fields[f_label or f_id] = actually_selected
                                            filled_field_ids[f_label or f_id] = f_id
                                            if log_callback:
                                                log_callback(f"Self-healed [{f_label or f_id}] -> '{actually_selected}'")
                                elif el_type == "radio":
                                    if fix_val and str(fix_val).lower() not in ("none", "null", "undefined", "") and await _select_radio_option(target_frame, f_id, str(fix_val)):
                                        filled_fields[f_label or f_id] = str(fix_val)
                                        filled_field_ids[f_label or f_id] = f_id
                                        if log_callback:
                                            log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                                elif el_type == "checkbox":
                                    if fix_val and str(fix_val).lower() not in ("no", "false", "0", "unchecked", "none", "null"):
                                        await elem.check(force=True)
                                        filled_fields[f_label or f_id] = "checked"
                                        filled_field_ids[f_label or f_id] = f_id
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
                                        # Exact match first: "male" is literally a substring
                                        # of "female", so a bare containment check can pick
                                        # the wrong option when the wrong one happens to come
                                        # first in the dropdown's order.
                                        for opt_t in opt_texts:
                                            clean = opt_t.strip()
                                            if not clean or clean.lower() in ("select...", "select", "--", "choose"):
                                                continue
                                            if wanted == clean.lower():
                                                matched_opt = clean
                                                break
                                        if matched_opt is None:
                                            for opt_t in opt_texts:
                                                clean = opt_t.strip()
                                                clean_lower = clean.lower()
                                                if not clean or clean_lower in ("select...", "select", "--", "choose"):
                                                    continue
                                                is_gender_collision = (
                                                    (wanted == "male" and "female" in clean_lower)
                                                    or (wanted == "female" and clean_lower == "male")
                                                )
                                                if is_gender_collision:
                                                    continue
                                                if wanted in clean_lower or clean_lower in wanted:
                                                    matched_opt = clean
                                                    break
                                        if matched_opt:
                                            await elem.select_option(label=matched_opt)
                                            filled_fields[f_label or f_id] = matched_opt
                                            filled_field_ids[f_label or f_id] = f_id
                                            if log_callback:
                                                log_callback(f"Self-healed [{f_label or f_id}] -> '{matched_opt}'")
                                        elif log_callback:
                                            log_callback(f"Self-heal: no matching option for [{f_label or f_id}] wanting '{fix_val}'", lvl="warning")
                                else:
                                    # Never coerce an unknown field to the literal string "None"
                                    if fix_val and str(fix_val).lower() not in ("none", "null", "undefined", ""):
                                        await elem.fill(str(fix_val))
                                        filled_fields[f_label or f_id] = str(fix_val)
                                        filled_field_ids[f_label or f_id] = f_id
                                        if log_callback:
                                            log_callback(f"Self-healed [{f_label or f_id}] -> '{fix_val}'")
                            except Exception as fill_err:
                                logger.warning("Fill error on %s: %s", f_id, fill_err)



                await asyncio.sleep(0.5)

            # ─── VERIFIED AUTONOMY SUBMISSION POLICY GATE ─────────────────────
            # 1. Collect all answer resolutions from form filling
            #
            # resolve_answer() is called again here only to get question_type
            # classification for cross-field validation below — NOT to
            # re-derive the answer. It's called with no `options` (the actual
            # live dropdown/radio options aren't available anymore at this
            # point), so for a Yes/No-style question it can classify and
            # resolve differently than the original fill-time call did (which
            # saw the real options) and return a different answer entirely.
            # Verification then compares that fresh, options-blind guess
            # against the live DOM value under the field's own label — an
            # unrelated field can share enough of that label as a substring to
            # get matched, so a wrong guess here surfaces as a nonsensical
            # mismatch on a completely different question (observed live: a
            # location answer flagged as conflicting with an office-days
            # Yes/No field's selected value). The fix is field_id: every fill
            # site above now records the live DOM element id it actually
            # wrote into (filled_field_ids), so verification can pair each
            # resolution back to its own element by id instead of by fuzzy
            # label/substring matching. The answer itself is also overwritten
            # with `ans` — the real value this function wrote into the DOM —
            # rather than trusting a fresh re-resolution's guess.
            form_resolutions: list[AnswerResolution] = []
            for lbl, ans in filled_fields.items():
                res = resolve_answer(
                    question_text=lbl,
                    profile=profile,
                    answer_lib=answer_lib,
                    field_id=filled_field_ids.get(lbl, ""),
                )
                res.answer = ans
                form_resolutions.append(res)

            # 2. Run cross-field deterministic validation
            cross_field_report = validate_answers(form_resolutions, profile)

            # 2b. Record any NEW high-risk contradictions as persistent blocks.
            # These persist on the job_item so retries cannot bypass them.
            from app.services.application_assistant.cross_field_validator import RULE_DOMAIN_MAP
            from app.services.application_assistant.submission_policy import HIGH_RISK_CONTRADICTION_DOMAINS
            existing_contradictions: list[dict[str, Any]] = list(job_item.get("blockingContradictions") or [])
            existing_rules = {bc.get("rule") for bc in existing_contradictions}
            for err in cross_field_report.blocking_errors:
                domain = getattr(err, 'domain', '') or RULE_DOMAIN_MAP.get(err.rule, '')
                if domain in HIGH_RISK_CONTRADICTION_DOMAINS and err.rule not in existing_rules:
                    existing_contradictions.append({
                        "domain": domain,
                        "rule": err.rule,
                        "fieldId": err.field_id,
                        "question": err.question,
                        "reason": err.reason,
                        "answer": str(err.answer) if hasattr(err, 'answer') else "",
                        "recordedAt": now_iso(),
                    })
                    existing_rules.add(err.rule)
            if existing_contradictions:
                job_item["blockingContradictions"] = existing_contradictions
                logger.warning(
                    "Recorded %d blocking contradiction(s) on job %s",
                    len(existing_contradictions), job_id,
                )

            # 3. Read back live browser DOM state
            dom_verification = await verify_browser_dom_state(target_frame, form_resolutions, profile)

            # 3b. Compute field verification status from DOM read-back
            field_verification_status = "FIELD_VALUES_VERIFIED"
            if dom_verification and (not dom_verification.passed or dom_verification.issues):
                has_blocking_dom = any(i.severity == "BLOCKING" for i in (dom_verification.issues or []))
                field_verification_status = "FIELD_VALUES_MISMATCH" if has_blocking_dom else "FIELD_VALUES_VERIFIED"

            # 4. Evaluate centralized SubmissionPolicy (with persistent blocks)
            policy_result = SubmissionPolicy.evaluate(
                resolutions=form_resolutions,
                validation_report=cross_field_report,
                dom_verification=dom_verification,
                profile=profile,
                blocking_contradictions=job_item.get("blockingContradictions"),
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
                    await page.screenshot(path=str(pre_screenshot_path), full_page=True, timeout=5000)
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
                await page.screenshot(path=str(pre_screenshot_path), full_page=True, timeout=5000)
            except Exception:
                pass

            # A cookie-consent overlay left on screen blocks every subsequent
            # click with "intercepts pointer events" (observed live on NICE's
            # careers page, a CookieYes-style ".cky-overlay") — dismiss it
            # before attempting the submit click rather than only discovering
            # the block after the click has already started retrying.
            for consent_sel in (
                'button:has-text("Accept All")',
                'button:has-text("Accept all")',
                'button:has-text("Accept Cookies")',
                'button:has-text("I Accept")',
                'button:has-text("Accept")',
                '.cky-btn-accept',
                '#onetrust-accept-btn-handler',
            ):
                try:
                    consent_btn = page.locator(consent_sel).first
                    if await consent_btn.count() > 0 and await consent_btn.is_visible():
                        await consent_btn.click(timeout=2000)
                        await asyncio.sleep(0.3)
                        break
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

            async def _find_real_submit_button(scope: Any) -> Any:
                for sel in submit_selectors:
                    candidates = scope.locator(sel)
                    for idx in range(await candidates.count()):
                        candidate = candidates.nth(idx)
                        if not await candidate.is_visible():
                            continue
                        # A bare button[type="submit"] selector matches ANY
                        # submit button on the page, not just the
                        # application form's — observed live: it grabbed a
                        # site-wide header search icon (title="Search",
                        # class="header-search-icon") on NICE's careers
                        # page, clicked it instead of ever finding the real
                        # submit button, and the run timed out waiting for
                        # that irrelevant button to become clickable.
                        title = (await candidate.get_attribute("title") or "").lower()
                        aria = (await candidate.get_attribute("aria-label") or "").lower()
                        cls = (await candidate.get_attribute("class") or "").lower()
                        if any("search" in v for v in (title, aria, cls)):
                            continue
                        return candidate
                return None

            submit_button = await _find_real_submit_button(target_frame)
            if not submit_button:
                submit_button = await _find_real_submit_button(page)

            if not submit_button:
                # "Submit button not found" is misleading when the page never
                # had an application form to begin with — observed live on two
                # postings: a Greenhouse URL that now 302s to the company's
                # careers homepage (posting pulled), and a job *description*
                # page whose form only mounts after an "Apply" click. Both
                # reported as submit-button failures and looked like selector
                # bugs. Distinguish them so a dead posting is triaged as
                # expired instead of retried against a page that can never
                # submit.
                form_present = False
                try:
                    for probe in ('form', 'input[type="file"]', 'input[name*="resume" i]'):
                        for scope in (target_frame, page):
                            try:
                                if await scope.locator(probe).count() > 0:
                                    form_present = True
                                    break
                            except Exception:
                                continue
                        if form_present:
                            break
                except Exception:
                    pass

                if form_present:
                    error_msg = "Submit button not found on application page"
                else:
                    try:
                        landed_url = page.url
                    except Exception:
                        landed_url = ""
                    error_msg = (
                        "No application form on the page — the posting appears to be closed or "
                        f"redirected (landed on {landed_url or 'an unknown URL'})"
                    )

                return {
                    "submitted": False,
                    "error": error_msg,
                    "noApplicationForm": not form_present,
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

            # ─── WAIT FOR SUBMISSION RESOLUTION (CONFIRMATION OR ERRORS) ───────
            conf_phrases = [
                "thank you for applying",
                "thank you for your application",
                "we have received your application",
                "your application was submitted",
                "your application has been received",
                "your application has been submitted to",
                "we've received your application",
                "thank you for taking the time to apply",
                "successfully submitted",
                "submission successful",
                "your response has been recorded",
                "thanks for applying",
                "thank you for your interest",
            ]
            
            logger.info("Waiting for external site submission confirmation...")
            start_wait = asyncio.get_event_loop().time()
            max_wait_sec = 45.0
            submission_resolved = False

            while (asyncio.get_event_loop().time() - start_wait) < max_wait_sec:
                cur_url = page.url.lower()
                if any(x in cur_url for x in ["/confirmation", "/thank_you", "/thank-you", "/applied", "/success", "submitted=true", "thanks"]):
                    logger.info("Submission confirmed via URL redirect: %s", page.url)
                    submission_resolved = True
                    break

                # Check page body
                try:
                    p_text = (await page.inner_text("body", timeout=1000)).lower()
                    if any(ph in p_text for ph in conf_phrases):
                        logger.info("Submission confirmed via page DOM text.")
                        submission_resolved = True
                        break
                except Exception:
                    pass

                # Check frame body if different
                if target_frame and target_frame != page:
                    try:
                        f_text = (await target_frame.inner_text("body", timeout=1000)).lower()
                        if any(ph in f_text for ph in conf_phrases):
                            logger.info("Submission confirmed via frame DOM text.")
                            submission_resolved = True
                            break
                    except Exception:
                        pass

                # Check confirmation elements
                try:
                    conf_el = page.locator('[data-qa="application-success"], [data-qa="confirmation"], #application_confirmation, .application-confirmation, [class*="ApplicationConfirmation"], [class*="confirmation"]')
                    if await conf_el.count() > 0 and await conf_el.first.is_visible():
                        logger.info("Submission confirmed via confirmation element.")
                        submission_resolved = True
                        break
                except Exception:
                    pass

                # Check if validation errors appeared
                _, active_errs = await _extract_dom_form_state(target_frame)
                if active_errs:
                    logger.warning("Submission rejected with validation errors: %s", active_errs)
                    break

                await asyncio.sleep(2.0)

            await asyncio.sleep(1.0)

            # Post-submission screenshot
            confirmation_url = page.url
            post_screenshot_path = SCREENSHOTS_DIR / f"{job_id}_confirmation.png"
            try:
                await page.screenshot(path=str(post_screenshot_path), full_page=True, timeout=10000)
            except Exception:
                pass

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
                field_verification_status=field_verification_status,
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
                await page.screenshot(path=str(err_screenshot), full_page=True, timeout=5000)
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
