"""Playwright Autopilot Live Submitter with Strict Pre-Submit & Post-Submit Verification."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from urllib.parse import urlparse
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
    PROFILE_EXACT,
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
# Where the assisted hand-off keeps its browser profile.
#
# An application a person finishes by hand is far easier when the browser
# remembers them: the addresses, phone numbers and answers Chrome has autofilled
# before, and any board they have already signed into. A throwaway context has
# none of that, so every assisted application started from nothing.
#
# This is CareerOS's own profile directory, deliberately not the user's live
# Chrome profile: Chrome locks its user-data-dir, so driving the real one would
# mean quitting every Chrome window first. Here the main browser stays open, and
# what the user types during an assisted application is remembered for the next.
ASSISTED_PROFILE_DIR = Path(
    os.environ.get("CAREEROS_ASSISTED_PROFILE_DIR")
    or (Path(__file__).resolve().parents[3] / "data" / "application_assistant" / "chrome-profile")
)
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
    reaches the employer - set_input_files uploads a file under its own
    on-disk basename, so a name like "apjob_<uuid>_aggressive.pdf" would be
    exactly what the ATS sees, reading as obviously machine-generated. Stage
    a copy under the candidate's normal resume filename, in a job-id-keyed
    subfolder so concurrent workers still never collide, and upload that
    instead - the original tailored file on disk keeps its traceable name.
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


async def _expand_combobox_options(page: Page, fields: list[dict[str, Any]], limit: int = 30) -> None:
    """Fill in option lists for comboboxes whose menu only exists while open.

    Greenhouse's custom dropdowns render no options until clicked and expose no
    aria-controls listbox, so a DOM read alone returns an empty option list.
    That is why questions the profile could answer - "Have you been employed by
    <company>", "are you open to relocation" - reached Review with
    {fieldType: "div", options: []}: the resolver had no options to match.

    Each menu is opened, read and closed again with Escape. Failures are
    ignored per field: a widget that will not open is no worse off than before.
    """
    opened = 0
    for field in fields:
        if opened >= limit:
            break
        if not field.get("isCombobox") or field.get("options"):
            continue
        idx = field.get("idx")
        if idx is None:
            continue
        try:
            handle = page.locator('input:not([type="hidden"]), textarea:not(.g-recaptcha-response):not([name*="recaptcha"]), select, [role="combobox"]').nth(int(idx))
            await handle.scroll_into_view_if_needed(timeout=2500)
            await handle.click(timeout=2500)
            await asyncio.sleep(0.45)
            options = await page.evaluate(
                "() => [...document.querySelectorAll('[role=\"option\"]')]"
                ".filter(o => o.offsetParent !== null)"
                ".map(o => (o.innerText || '').trim()).filter(Boolean).slice(0, 60)"
            )
            if options:
                field["options"] = options
            opened += 1
        except Exception:
            continue
        finally:
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.15)
            except Exception:
                pass


# Characters boards sprinkle around required markers that are invisible on
# screen but defeat exact matching against the answer library.
_INVISIBLE_CHARS = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)

# Words that are an answer, never a question.
_ANSWER_WORDS = frozenset({
    "yes", "no", "other", "true", "false", "n/a", "select...",
    "prefer not to say", "decline to answer", "i decline to answer",
})


def _looks_like_field_handle(text: str) -> bool:
    """True for an opaque id used where a question should be (CA_47143, QA_12203581)."""
    if not text:
        return True
    if re.fullmatch(r"[A-Za-z]{0,4}[_-]?\d{3,}", text):
        return True
    if re.fullmatch(r"[0-9a-f]{8,}", text, re.I):
        return True
    return re.search(r"[a-z]{3}", text, re.I) is None


def sanitize_field_label(raw: str) -> str:
    """Clean a question label, or return "" when it is not a question at all.

    The review list is only usable if every row states a question a person can
    answer. Three kinds of junk were reaching it: an option's own text ("Yes"),
    the field's internal id ("CA_47143"), and invisible word-joiner characters
    left around required markers. The browser-side extraction avoids all three
    now; this is the net underneath it, and unlike the injected JavaScript it
    can be tested directly.
    """
    text = (raw or "").translate(_INVISIBLE_CHARS)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[\s*:•\-]+$", "", text).strip()
    if not text:
        return ""
    if text.lower() in _ANSWER_WORDS:
        return ""
    if _looks_like_field_handle(text):
        return ""
    return text


async def _extract_dom_form_state(page: Page, expand_comboboxes: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
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

            // A radio *group* is one question - querySelectorAll returns every
            // individual <input> in it, so without dedup the same question
            // shows up once per option, each independently guessing its own
            // label via the (fragile) per-element fallback below. Two inputs
            // in the same group can land on different, wrong ancestor divs and
            // report different labels for what is really one question - one of
            // which can end up matching a *different* field's resolved answer
            // during verification (observed live: a location answer flagged as
            // conflicting with an unrelated Yes/No radio's selected value).
            // Emit exactly one entry per group, labeled via fieldset/legend
            // first - the same reliable signal the fill-side logic already
            // prefers for these groups - before falling back to nearby text.
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
            // Clean and sanity-check the label before trusting it.
            //
            // Three things were reaching the review list as "questions" that
            // are not questions at all, and each one makes the list unusable in
            // its own way:
            //   'Yes'          - an option's own text, grabbed by the
            //                    parent-innerText fallback below, so the user
            //                    is asked to answer a question called "Yes".
            //   'CA_47143'     - the field's id, used because nothing else was
            //   'QA_12203581'    found. An opaque token tells the user nothing
            //                    and the resolver nothing.
            //   '...*⁠:'   - word-joiner and zero-width characters that
            //                    boards sprinkle around required markers, which
            //                    defeat exact matching against the answer
            //                    library and look like mojibake on screen.
            var cleanLabel = function (raw) {
                return (raw || '')
                    .replace(/[​‌‍⁠﻿]/g, '')  // zero-width / word joiner
                    .replace(/\s+/g, ' ')
                    .replace(/[\s*:•\-]+$/, '')                     // trailing required markers
                    .trim();
            };
            // An id-shaped token (CA_47143, QA_12203581, q_8f3a2b, 12345) is a
            // handle, not a question.
            var looksLikeId = function (text) {
                if (!text) return true;
                if (/^[A-Za-z]{0,4}[_-]?\d{3,}$/.test(text)) return true;
                if (/^[0-9a-f]{8,}$/i.test(text)) return true;
                return !/[a-z]{3}/i.test(text);
            };
            // The option list is built further down, so this compares against
            // the control's own value and the handful of words that are always
            // an answer rather than a question.
            var isOptionText = function (text) {
                if (!text) return false;
                var t = text.toLowerCase().trim();
                var own = (el.value || '').toLowerCase().trim();
                if (own && own !== 'on' && own === t) return true;
                return ['yes', 'no', 'other', 'true', 'false', 'n/a', 'select...',
                        'prefer not to say', 'decline to answer',
                        'i decline to answer'].indexOf(t) !== -1;
            };

            label = cleanLabel(label);
            if (!label || isOptionText(label) || looksLikeId(label)) {
                // Try the honest sources in turn before giving up on the id.
                var better = '';
                try {
                    var lb = el.getAttribute('aria-labelledby');
                    if (lb) {
                        var lbEl = document.getElementById(lb.split(/\s+/)[0]);
                        if (lbEl) better = cleanLabel(lbEl.innerText);
                    }
                } catch (err) {}
                if ((!better || isOptionText(better)) && el.closest) {
                    var grp = el.closest('fieldset, [role="group"], [role="radiogroup"]');
                    if (grp) {
                        var lg2 = grp.querySelector('legend, .question-label, .field__label, label');
                        if (lg2) better = cleanLabel(lg2.innerText);
                    }
                }
                if (!better || isOptionText(better) || looksLikeId(better)) {
                    better = cleanLabel(ariaLabel) || better;
                }
                label = better || '';
            }
            // Only fall back to a raw handle when there is genuinely nothing
            // else, and mark it so the reviewer can see it was never a label.
            if (!label) {
                var handle = cleanLabel(name) || cleanLabel(id);
                label = handle && !looksLikeId(handle) ? handle : (handle ? 'Unlabelled field (' + handle + ')' : '');
            }

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

            // Ashby renders its custom questions as radio groups that carry NO
            // requiredness signal anywhere in the DOM: the individual inputs
            // have required=false, the fieldset has no aria-required, and the
            // question title has no '*'. Requiredness lives only in the app's
            // own state and surfaces after submit as "Missing entry for
            // required field: ...". So for a choice group, required===false is
            // an ABSENCE OF INFORMATION, not evidence the question is optional
            // - and the pre-submit audit must not read it as a pass.
            // Observed live: a Whatnot/Ashby application audited "100% PASS"
            // with two unanswered required questions and was rejected on submit.
            var requirednessUnknown = (inputType === 'radio' || inputType === 'checkbox' || isCombobox) && !isRequired;

            // Option list. Without this the resolver was handed
            // {fieldType: "div", options: []} for every custom dropdown and had
            // nothing to match against, so the question went to Review even
            // when the profile held the answer. Native selects and comboboxes
            // that point at a listbox can be read right here; the ones whose
            // menu only exists while open are handled by the Python pass below.
            var opts = [];
            if (el.tagName.toLowerCase() === 'select') {
                for (var oi = 0; oi < el.options.length; oi++) {
                    var otext = (el.options[oi].text || '').trim();
                    if (otext) opts.push(otext);
                }
            } else if (isCombobox) {
                var lbId = el.getAttribute('aria-controls') || el.getAttribute('aria-owns') || '';
                var lb = lbId ? document.getElementById(lbId) : null;
                if (lb) {
                    var lopts = lb.querySelectorAll('[role="option"], option');
                    for (var li = 0; li < lopts.length; li++) {
                        var ltext = (lopts[li].innerText || lopts[li].textContent || '').trim();
                        if (ltext) opts.push(ltext);
                    }
                }
            }

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
                requirednessUnknown: requirednessUnknown,
                value: val,
                options: opts
            });
        }

        return { fields: fields, errors: errors };
    }
    """
    try:
        data = await page.evaluate(js_code)
        fields = data.get("fields", [])
        # Second net under the browser-side cleaning: a label that is not
        # a question is dropped rather than shown to the user as one.
        for field in fields:
            field["label"] = sanitize_field_label(field.get("label", ""))
        if expand_comboboxes and fields:
            await _expand_combobox_options(page, fields)
        return fields, data.get("errors", [])
    except Exception as ex:
        logger.warning("Error extracting DOM state: %s", ex)
        return [], []


# Questions employers are legally required to present as voluntary. Leaving one
# blank is a valid, complete answer, so an unanswered one must never block a
# submission - which matters because these are almost always radio groups, and
# the audit below otherwise treats an unanswered choice group as unresolved.
_VOLUNTARY_DISCLOSURE_PATTERNS = (
    "gender", "race", "ethnic", "hispanic", "latino", "veteran", "disability",
    "disabled", "self-identif", "self identif", "eeo", "equal employment",
    "protected veteran", "sexual orientation", "transgender", "pronoun",
)


def _is_voluntary_disclosure(label: str) -> bool:
    """True when a question is an optional demographic self-identification."""
    text = (label or "").lower()
    return any(pattern in text for pattern in _VOLUNTARY_DISCLOSURE_PATTERNS)


async def _advance_workday_to_form(page: Any, log_callback: Any = None) -> str:
    """Move a Workday posting from its chooser to the real application form.

    Returns:
        "form"          - an application form is reachable on the current page.
        "needs_account" - the sign-in / create-account step is in the way.
        "unknown"       - neither could be established.

    Workday serves the posting, the "/apply" chooser and the wizard as three
    different pages, and only the third has inputs. Nothing here types a
    password or creates an account; it only clicks through the menu so the
    person is handed the page they actually need, or so the runner can report
    the sign-in gate accurately instead of "no application form".
    """
    url = page.url or ""
    try:
        # The posting URL and the apply URL are different pages; the chooser
        # only exists at /apply.
        if "/apply" not in url:
            target = url.split("?")[0].rstrip("/") + "/apply"
            await page.goto(target, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3.0)

        for label in ("Apply Manually", "Autofill with Resume", "Use My Last Application"):
            try:
                choice = page.get_by_role("button", name=label).first
                if await choice.count() == 0:
                    choice = page.get_by_text(label, exact=True).first
                if await choice.count() and await choice.is_visible():
                    if log_callback:
                        log_callback(f"Workday: choosing '{label}' on the apply menu...")
                    await choice.click(timeout=8000)
                    await asyncio.sleep(4.0)
                    break
            except Exception:
                continue

        state = await page.evaluate(
            "() => {"
            "  const pw = document.querySelectorAll('input[type=password]').length;"
            "  const text = (document.body.innerText || '').toLowerCase();"
            "  const gate = pw > 0 || /create account|sign in to (?:your )?account/.test(text);"
            "  const fields = document.querySelectorAll("
            "     'input[type=text],input[type=email],input[type=tel],textarea,select,input[type=file]').length;"
            "  return {gate, fields};"
            "}"
        )
        if state.get("gate"):
            return "needs_account"
        if int(state.get("fields") or 0) > 0:
            if log_callback:
                log_callback("Workday: already signed in — the application form is reachable.")
            return "form"
        return "unknown"
    except Exception as exc:
        logger.warning("Could not advance the Workday flow: %s", exc)
        return "unknown"


_OPEN_ENDED_HINTS = (
    "why ", "what ", "how ", "describe", "tell us", "tell me", "explain",
    "share ", "cover letter", "in your own words", "interest",
)


def _is_open_ended_question(dom_field: dict[str, Any] | None, label: str) -> bool:
    """True for a free-text question no profile field can answer.

    Deliberately narrow: a textarea, or a plain text input asking something
    essay-shaped. Anything with options is a choice question and belongs to the
    resolver, which can pick honestly from what is offered.
    """
    field = dom_field or {}
    if field.get("options"):
        return False
    tag = str(field.get("tag") or "").lower()
    ftype = str(field.get("type") or "").lower()
    if tag == "textarea":
        return True
    if tag == "input" and ftype in ("text", ""):
        low = (label or "").lower()
        return any(hint in low for hint in _OPEN_ENDED_HINTS) and len(label or "") > 15
    return False


_EXPLANATION_HINTS = (
    "please explain", "explain why", "explain how", "please describe",
    "tell us", "tell me", "please state where", "please specify",
    "in your own words", "please elaborate", "please provide details",
    "what is the basis of", "if so,", "if yes,",
)

_TOKEN_ANSWERS = frozenset({
    "yes", "no", "y", "n", "true", "false", "n/a", "na", "none",
    "checked", "agree", "i agree", "acknowledge",
})


def _is_token_answer_in_prose_box(
    dom_field: dict[str, Any] | None, label: str, value: Any
) -> bool:
    """True when a one-word answer is about to be typed into an essay field.

    A question can open with a Yes/No clause and still want a paragraph ("Have
    you recently worked at a FinTech company? If yes, please state where."),
    and a resolver keyed on the first clause answers the wrong half of it. The
    field's own shape settles the argument: an options-less textarea is asking
    for prose whatever the wording suggests, so a bare token there is a
    non-answer rather than a short one.
    """
    field = dom_field or {}
    if field.get("options"):
        return False
    text = str(value or "").strip()
    if not text:
        return False

    is_textarea = str(field.get("tag") or "").lower() == "textarea"
    low = (label or "").lower()
    wants_prose = is_textarea or any(hint in low for hint in _EXPLANATION_HINTS)
    if not wants_prose:
        return False

    if text.lower().strip(" .!") in _TOKEN_ANSWERS:
        return True
    # A profile token ("Washington", "Microsoft") is no better an answer to an
    # essay question than "Yes" is, so anything under a handful of words in a
    # textarea that asked to be explained is treated the same way.
    if is_textarea and any(hint in low for hint in _EXPLANATION_HINTS):
        return len(text.split()) < 5
    return False


async def _load_settings_for_generation() -> dict[str, Any]:
    """Settings for the answer generator, read off the main thread."""
    try:
        from app.services.application_assistant.persistence import get_settings

        with session_scope() as db:
            return get_settings(db)
    except Exception:
        return {}


def _keyboard(page: Any) -> Any:
    """Return a real Keyboard for either a Page or a Frame.

    Greenhouse's application form is frequently reached as a Frame, and Frame
    has no `.keyboard` - only Page does. Every `page.keyboard...` call in the
    fill path therefore raised AttributeError the moment the form lived in a
    frame, and those raises were caught and logged at debug level, so whole
    passes (notably the searchable-combobox typing pass that fills School and
    Discipline) silently did nothing at all rather than failing loudly.
    """
    kb = getattr(page, "keyboard", None)
    if kb is not None:
        return kb
    return page.page.keyboard


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

        # Locate the surrounding control or wrapper, or check inside cb_el if cb_el is a container
        inner_control = cb_el.locator('div.select__control, div[class*="control"], [role="combobox"]').first
        if await inner_control.count() > 0:
            target = inner_control
        else:
            wrapper = page.locator(f'div.select__control:has([id="{cb_id}"]), div[class*="control"]:has([id="{cb_id}"]), div:has(> div > [id="{cb_id}"]), div:has(> [id="{cb_id}"])').first
            target = wrapper if await wrapper.count() > 0 else cb_el

        # Click to open the dropdown menu
        await target.click(force=True)
        await asyncio.sleep(0.3)

        # Look for visible options in the document.
        #
        # Read every option's text in ONE evaluate rather than walking the
        # locator with .nth(i) + is_visible() + inner_text(). That loop cost two
        # browser round-trips per option and was unbounded, and the selector
        # below is deliberately broad ('div[class*="option"]' matches a lot on a
        # real page). On a Greenhouse embed carrying a 240-entry country
        # dropdown it meant hundreds of round-trips for a single field, which is
        # what pushed Coinbase and Samsara past the 480s submission watchdog
        # while they sat in the self-healing loop.
        options_loc = page.locator('.select__option, div[class*="option"], [role="option"]')
        try:
            option_texts: list[str] = await page.eval_on_selector_all(
                '.select__option, div[class*="option"], [role="option"]',
                "els => els.map(el => ("
                "  (el.offsetWidth || el.offsetHeight || el.getClientRects().length)"
                "    ? (el.innerText || '').trim() : ''"
                "))",
            )
        except Exception:
            option_texts = []
        opt_count = len(option_texts)

        if opt_count > 0:
            # 1. Look for exact or partial case-insensitive match
            clean_search = search_text.strip().lower()
            best_opt = None
            best_text = ""

            fallback_opt = None
            fallback_text = ""
            for i, opt_text in enumerate(option_texts):
                opt_text = (opt_text or "").strip()
                opt_text_lower = opt_text.lower()
                if not opt_text or opt_text_lower in ("select...", "select", "--", "choose"):
                    continue
                opt = options_loc.nth(i)

                if clean_search and opt_text_lower == clean_search:
                    best_opt = opt
                    best_text = opt_text
                    break

                # "male" is literally a substring of "female", so containment
                # alone can match the wrong option - only accept it as a
                # fallback, and never let it beat an exact match found later.
                is_gender_collision = (
                    (clean_search == "male" and "female" in opt_text_lower)
                    or (clean_search == "female" and opt_text_lower == "male")
                )
                # Containment alone is not a match when both sides are
                # comma-separated place names: "seattle, wa" is a substring of
                # "South Seattle, Washington, United States", which is a
                # different city. Require the leading segment to agree before
                # accepting a containment hit.
                heads_agree = (
                    opt_text_lower.split(",")[0].strip() == clean_search.split(",")[0].strip()
                    or "," not in opt_text_lower
                )
                if (
                    clean_search
                    and not is_gender_collision
                    and heads_agree
                    and fallback_opt is None
                    and (clean_search in opt_text_lower or opt_text_lower in clean_search)
                ):
                    fallback_opt = opt
                    fallback_text = opt_text

            if best_opt is None and fallback_opt is not None:
                best_opt = fallback_opt
                best_text = fallback_text

            # Only click a real match. Falling back to "whichever option is
            # first" when nothing matches search_text isn't a fallback, it's a
            # fabricated answer - observed live: a bad search term ("Auburn")
            # against a Yes/No dropdown blindly clicked "Yes" (the first
            # option), then the caller recorded the *original* search term as
            # the intended answer, guaranteeing a nonsensical mismatch against
            # the real DOM value at verification time. Leaving the field
            # untouched here means it correctly stays flagged for review.
            if best_opt:
                await best_opt.click(force=True)
                await asyncio.sleep(0.2)
                return best_text
            await _keyboard(page).press("Escape")
            return ""

        # Fallback: type only if text-fillable (never on file or hidden inputs)
        try:
            el_type = (await cb_el.get_attribute("type") or "").lower()
            if el_type != "file":
                await cb_el.fill("")
                await cb_el.type(str(search_text), delay=20)
                await asyncio.sleep(0.2)
                await _keyboard(page).press("ArrowDown")
                await asyncio.sleep(0.1)
                await _keyboard(page).press("Enter")
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
                    await el.scroll_into_view_if_needed(timeout=2500)
                    await el.fill(str(value), timeout=3500)
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
            inner_radio = source.locator('input[type="radio"]').first
            if await inner_radio.count() > 0:
                name = await inner_radio.get_attribute("name")
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
# negotiation-sensitive disclosures - demographics, pay, academic scores - and
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
    field_id set - without it, DOM verification has to pair an answer back to
    its element by fuzzy label matching, which can pair the wrong two fields.
    """
    filled: dict[str, str] = {}
    filled_ids: dict[str, str] = {}
    all_resolutions: list[AnswerResolution] = []

    # Snapshot ids up front rather than holding Locator.all()'s positional
    # (nth-indexed) references: clicking an earlier combobox's autocomplete
    # suggestion can insert/remove sibling DOM nodes, which reflows those
    # positional locators onto a *different* physical element for later
    # iterations - observed as e.g. the Location field's resolved answer
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
            # state value now, before we open the menu - if the resolved
            # answer later turns out to already match it, we skip touching
            # the control entirely rather than opening/clicking it and
            # risking an unnecessary re-selection landing on the wrong option.
            preexisting_value = (await el.evaluate("""el => {
                var wrapper = el.closest('div.select__control, div[class*="select__control"]');
                if (!wrapper) return '';
                var sv = wrapper.querySelector('[class*="singleValue"], [class*="single-value"]');
                return sv ? sv.textContent.trim() : '';
            }""") or "").strip()

            # Collect available options by opening the dropdown.
            #
            # Confirm THIS control actually opened (aria-expanded on its own
            # input) rather than waiting on a document-wide menu selector,
            # which matches any other field's open menu and made a failed open
            # look like a success. React-Select also opens on ArrowDown, so a
            # click that lands on a non-interactive part of the control gets a
            # keyboard retry before we give up on the field.
            await target_to_open.scroll_into_view_if_needed()

            async def _is_open() -> bool:
                try:
                    return await el.evaluate("e => e.getAttribute('aria-expanded') === 'true'")
                except Exception:
                    return False

            # Three attempts, not two: React-Select controls further down a long
            # Greenhouse form are routinely still mounting when their turn comes,
            # and both the click and the ArrowDown retry then land on a control
            # that is not listening yet. Observed live on Robinhood's "preferred
            # office location" and "disability status" - two *required* fields
            # that read zero options and were dropped without a trace. The third
            # pass re-clicks after a longer settle.
            for attempt in range(3):
                try:
                    if attempt == 1:
                        await el.focus()
                        await _keyboard(page).press("ArrowDown")
                    else:
                        if attempt == 2:
                            await asyncio.sleep(0.6)
                            await target_to_open.scroll_into_view_if_needed()
                        await target_to_open.click(force=True)
                except Exception:
                    pass
                for _ in range(12):
                    if await _is_open():
                        break
                    await asyncio.sleep(0.1)
                if await _is_open():
                    break

            # Fast evaluate to get all option texts in 1 ms without slow per-element Playwright RPCs.
            #
            # SCOPED TO THIS COMBOBOX ONLY. This used to run a document-wide
            # querySelectorAll for '.select__option, [role="option"]', which
            # silently read *another* field's open menu whenever this control
            # failed to open - and Greenhouse renders its phone country-code
            # picker as a React-Select (.select__option), so the old
            # '.iti, .iti__country-list' exclusion never caught it. Observed
            # live: "In which country/region do you have citizenship?" was
            # answered "Lebanon" and "Do you permanently reside within the
            # United States?" was handed a 240-country list for a Yes/No
            # question. Reading the wrong field's options doesn't just leave a
            # field blank, it puts a fabricated fact on a real application, so
            # options now come only from this input's own menu (via
            # aria-controls/aria-owns, else its own React-Select container).
            opt_data: list[str] = await page.evaluate("""(cid) => {
                var el = document.getElementById(cid);
                if (!el) return [];
                var scope = null;
                var owned = el.getAttribute('aria-controls') || el.getAttribute('aria-owns');
                if (owned) scope = document.getElementById(owned);
                if (!scope) {
                    // React-Select renders .select__menu as a sibling of
                    // .select__control inside the same container.
                    var container = el.closest('.select__container, [class*="select__container"]')
                        || (el.closest('.select__control, [class*="select__control"]') || {}).parentElement
                        || el.parentElement;
                    for (var up = 0; up < 4 && container; up++) {
                        var m = container.querySelector('.select__menu, div[class*="-menu"], [role="listbox"]');
                        if (m) { scope = m; break; }
                        container = container.parentElement;
                    }
                }
                if (!scope) return [];
                var opts = scope.querySelectorAll('.select__option, div[class*="-option"], [role="option"]');
                var res = [];
                for (var i = 0; i < opts.length; i++) {
                    if (opts[i].closest('.iti, .iti__country-list')) continue;
                    var t = (opts[i].innerText || '').trim();
                    var isVis = !!(opts[i].offsetWidth || opts[i].offsetHeight || opts[i].getClientRects().length || opts[i].offsetParent !== null);
                    if (t && isVis && t.toLowerCase().indexOf('select...') === -1 && t.toLowerCase().indexOf('choose') === -1) {
                        res.push(t);
                    }
                }
                return res;
            }""", cid)

            available_options: list[str] = opt_data or []

            if not available_options:
                # A searchable/async React-Select renders its menu only once
                # something has been typed - Greenhouse's School and Discipline
                # fields are exactly this. An empty menu here therefore does not
                # mean the control is broken or optional; it means the option
                # list does not exist until a search runs. Resolve without an
                # option list and let the dynamic typing pass below perform that
                # search. Bailing out here was why a required "School*" stayed
                # permanently empty and staged every education-collecting
                # application for review.
                probe = resolve_answer(
                    question_text=lbl_text,
                    profile=profile,
                    options=None,
                    answer_lib=answer_lib,
                    field_id=cid,
                )
                if not probe.answer:
                    # Never drop a control silently. A required dropdown that yields
                    # no options is indistinguishable, in the logs, from one that was
                    # deliberately skipped - which is exactly why two required
                    # Robinhood fields sat empty with nothing recorded anywhere to
                    # say why the run had not touched them.
                    logger.warning(
                        "Combobox '%s' (id=%s) opened no options%s - leaving it empty",
                        lbl_text[:60], cid, " [REQUIRED]" if is_required else "",
                    )
                    await _keyboard(page).press("Escape")
                    await asyncio.sleep(0.05)
                    continue
                all_resolutions.append(probe)
                resolution = probe
            elif len(available_options) == 1:
                # A field with exactly one real option (e.g. a GDPR/data-
                # processing "Acknowledge/Confirm" disclosure) isn't a
                # judgment call - there's nothing to classify or guess,
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
                # them - that old check misclassified genuine country
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
                # against a separately-computed label from DOM-state extraction -
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
                await _keyboard(page).press("Escape")
                await asyncio.sleep(0.05)
                continue

            if preexisting_value and preexisting_value.lower() == target_text.strip().lower():
                filled[lbl_text[:50]] = preexisting_value
                filled_ids[lbl_text[:50]] = cid
                await _keyboard(page).press("Escape")
                await asyncio.sleep(0.05)
                continue

            if resolution.blocking_errors:
                logger.warning("Combobox '%s' blocked: %s", lbl_text[:50], resolution.blocking_errors)
                await _keyboard(page).press("Escape")
                await asyncio.sleep(0.05)
                continue

            # Find and click the matching option by text
            matched = False
            target_lower = target_text.strip().lower()

            # 1. Exact or partial match click via fast locator. Exact matches
            # are checked across every option before any substring fallback -
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
                target_head = target_lower.split(",")[0].strip()
                for opt_str in available_options:
                    opt_lower = opt_str.strip().lower()
                    is_gender_collision = (
                        (target_lower == "male" and "female" in opt_lower)
                        or (target_lower == "female" and opt_lower == "male")
                    )
                    if is_gender_collision:
                        continue
                    # Containment across comma-separated place names picks the
                    # wrong place: "seattle, wa" is a substring of "South
                    # Seattle, Washington, United States", and whichever such
                    # option happens to come first in the menu was accepted -
                    # which is how a correctly-selected "Seattle, Washington,
                    # United States" got replaced with a city the candidate
                    # does not live in. Require the leading segment to agree
                    # before a containment hit counts.
                    if "," in opt_lower and "," in target_lower:
                        if opt_lower.split(",")[0].strip() != target_head:
                            continue
                    elif "," in opt_lower and target_head and opt_lower.split(",")[0].strip() != target_head:
                        continue
                    if target_lower in opt_lower or opt_lower in target_lower:
                        candidate_str = opt_str
                        break
            if candidate_str is not None:
                exact_pattern = re.compile(rf"^\s*{re.escape(candidate_str.strip())}\s*$", re.IGNORECASE)
                opt_to_click = page.locator('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option, [role="option"]:not(.iti__country)').filter(has_text=exact_pattern).first
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
                    await _keyboard(page).type(target_text, delay=20)

                    visible_opts = page.locator('.select__menu .select__option, div[class*="-menu"] div[class*="-option"], .select__option')
                    # A searchable React-Select queries the server for its
                    # options; Greenhouse's School field takes ~1.5s to answer,
                    # and until it does the menu still shows the *pre-typing*
                    # default list. Waiting for a non-empty menu is therefore
                    # not enough - that list was never empty. Re-scan until a
                    # real match for what we typed shows up, and only settle
                    # for a positional fallback once the search has had time.
                    chosen = None
                    fallback = None
                    # A location typeahead answers "Seattle, WA" with a list
                    # whose first entry can be a *different* city ("South
                    # Seattle, Washington, United States"). Taking the first
                    # option put a city the candidate does not live in onto real
                    # applications, so an option whose own leading segment
                    # equals ours outranks mere document order.
                    segment_match = None
                    prefix_match = None
                    target_head = target_lower.split(",")[0].strip()
                    opt_count = 0
                    for _attempt in range(30):
                        await asyncio.sleep(0.1)
                        chosen = segment_match = prefix_match = fallback = None
                        opt_count = await visible_opts.count()
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
                            if segment_match is None and target_head and c_txt_lower.split(",")[0].strip() == target_head:
                                segment_match = (cand, c_txt)
                            if prefix_match is None and target_lower and c_txt_lower.startswith(target_lower):
                                prefix_match = (cand, c_txt)
                        if chosen or segment_match or prefix_match:
                            break
                    pick = chosen or segment_match or prefix_match or fallback
                    if pick:
                        await pick[0].click(force=True)
                        filled[lbl_text[:50]] = pick[1]
                        filled_ids[lbl_text[:50]] = cid
                        matched = True
                        await asyncio.sleep(0.1)
                except Exception as dyn_err:
                    logger.warning("Combobox dynamic search error on %s: %s", cid, dyn_err)

            if not matched:
                logger.warning(
                    "Combobox '%s': target '%s' not found in %d options, skipping (NO random fallback)",
                    lbl_text[:50], target_text, len(available_options),
                )
                await _keyboard(page).press("Escape")
                await asyncio.sleep(0.05)

        except Exception as ex:
            logger.debug("Combobox error: %s", ex)

    return filled, filled_ids


async def _fill_greenhouse_employment_rows(
    page: Any,
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Fill Greenhouse's structured Employment rows from the candidate's history.

    These are required text inputs with stable, index-suffixed ids
    (company-name-0, title-0, start-date-year-0, ...) and no question wording the
    generic label-keyword pass recognises, so the whole block was being left
    empty and the application staged for review. The month fields are
    comboboxes and are handled by the existing combobox pass; only the text
    inputs and the "Current role" checkbox are driven here.

    Every value comes from profile["workExperience"] via resolve_answer - a row
    the profile does not have stays empty rather than being invented.
    """
    filled: dict[str, str] = {}
    filled_ids: dict[str, str] = {}

    field_ids: list[str] = await page.eval_on_selector_all(
        'input[id^="company-name-"], input[id^="title-"], '
        'input[id^="start-date-year-"], input[id^="end-date-year-"]',
        "els => els.map(e => e.id)",
    )

    # Tick "Current role" first. It is what makes an ongoing job truthful on this
    # form, and Greenhouse disables that row's end-date inputs once it is set -
    # so doing it before anything else also stops the verifier from reporting
    # those (now inapplicable) required fields as unfilled.
    current_ids: list[str] = await page.eval_on_selector_all(
        'input[type="checkbox"][id^="current-role-"]', "els => els.map(e => e.id)"
    )
    history = profile.get("workExperience") or []
    for cid in current_ids:
        try:
            m = re.match(r"^current-role-(\d+)", cid)
            if not m:
                continue
            idx = int(m.group(1))
            if idx >= len(history) or not (history[idx] or {}).get("currentlyEmployed"):
                continue
            box = page.locator(f'[id="{cid}"]').first
            if await box.count() == 0 or not await box.is_visible():
                continue
            if not await box.is_checked():
                await box.check(force=True)
                await asyncio.sleep(0.2)
            filled[f"Current role {idx}"] = "checked"
            filled_ids[f"Current role {idx}"] = cid
        except Exception as ex:
            logger.debug("Employment current-role checkbox error: %s", ex)

    for fid in field_ids:
        try:
            el = page.locator(f'[id="{fid}"]').first
            if await el.count() == 0 or not await el.is_visible():
                continue
            if await el.is_disabled():
                continue
            if (await el.input_value()).strip():
                continue

            lbl = ""
            lbl_el = page.locator(f'label[for="{fid}"]').first
            if await lbl_el.count() > 0:
                lbl = (await lbl_el.inner_text()).strip()
            if not lbl:
                continue

            resolution = resolve_answer(
                question_text=lbl,
                profile=profile,
                options=None,
                answer_lib=answer_lib,
                field_id=fid,
            )
            if not resolution.answer:
                continue

            await el.fill(resolution.answer)
            await asyncio.sleep(0.1)
            filled[lbl[:50]] = resolution.answer
            filled_ids[lbl[:50]] = fid
        except Exception as ex:
            logger.debug("Employment field '%s' error: %s", fid, ex)

    return filled, filled_ids


_STATE_ABBREVIATIONS = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt", "nebraska": "ne",
    "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or",
    "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}


def _state_tokens(profile: dict[str, Any]) -> set[str]:
    """Every spelling of the candidate's state, lowercased."""
    tokens: set[str] = set()
    raw = str(profile.get("state") or "").strip().lower()
    if raw:
        tokens.add(raw)
        abbreviation = _STATE_ABBREVIATIONS.get(raw)
        if abbreviation:
            tokens.add(abbreviation)
        if len(raw) == 2:
            tokens.add(raw)
            for name, code in _STATE_ABBREVIATIONS.items():
                if code == raw:
                    tokens.add(name)
    location = str(profile.get("location") or "")
    tail = [part.strip().lower() for part in location.split(",")[1:]]
    tokens.update(part for part in tail if part)
    return {t for t in tokens if t}


def _pick_location_option(
    option_texts: list[str], answer: str, profile: dict[str, Any]
) -> int | None:
    """Index of the suggestion that really is the candidate's home town.

    City names are not unique across states: typing "Auburn" for a candidate in
    Auburn, Washington offers Auburn, Alabama first, and a match on the leading
    segment alone happily takes it - which is how a real application went out
    saying the candidate lives in Alabama. So the state has to agree too, and a
    city-only match is accepted only when nothing better exists and the
    candidate's state is unknown.
    """
    target = answer.strip().lower()
    city = target.split(",")[0].strip()
    states = _state_tokens(profile)

    city_only: int | None = None
    for index, raw in enumerate(option_texts):
        text = (raw or "").strip().lower()
        if not text:
            continue
        if text == target:
            return index
        if text.split(",")[0].strip() != city:
            continue
        segments = {seg.strip() for seg in text.split(",")[1:]}
        if states and segments & states:
            return index
        if city_only is None:
            city_only = index
    if states:
        # The candidate's state is known and no suggestion matched it, so every
        # remaining candidate is a different place with the same name. Better to
        # leave the field empty and have it reviewed than to claim the wrong one.
        return None
    return city_only


async def _fill_ashby_fields(
    page: Any,
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Fill an Ashby application form.

    Ashby needs its own pass because nothing about its DOM matches the
    Greenhouse-shaped selectors used elsewhere:

    * every custom question's id and name is a bare UUID, so the only thing that
      identifies a field is its label text;
    * a Yes/No question is a pair of button elements carrying
      data-option="yes|no" with a hidden checkbox behind them, not a radio group;
    * the location field is an autocomplete input with role="combobox" and no id
      at all, so a label[for=...] lookup cannot reach it.

    Every field is walked through its .ashby-application-form-field-entry
    container, the one stable hook Ashby does provide, and answered via the
    central resolver. Anything the resolver declines is left empty so the
    required-field check stages it for review rather than guessing.
    """
    filled: dict[str, str] = {}
    filled_ids: dict[str, str] = {}

    entries = page.locator(".ashby-application-form-field-entry")
    try:
        count = await entries.count()
    except Exception:
        return filled, filled_ids

    for index in range(count):
        entry = entries.nth(index)
        try:
            label_el = entry.locator("label").first
            if await label_el.count() == 0:
                continue
            label = (await label_el.inner_text()).strip().rstrip("*").strip()
            if not label:
                continue
            key = label[:50]
            field_path = await entry.get_attribute("data-field-path") or ""

            yes_no = entry.locator(".ashby-application-form-input-yesno-option")
            autocomplete = entry.locator('input[role="combobox"]')
            radios = entry.locator('input[type="radio"]')
            text_like = entry.locator(
                'input[type="text"], input[type="email"], input[type="tel"], '
                'input[type="url"], input[type="number"], textarea'
            )

            if await yes_no.count() > 0:
                pressed = await yes_no.evaluate_all(
                    "els => els.some(el => el.getAttribute('aria-pressed') === 'true')"
                )
                if pressed:
                    continue
                resolution = resolve_answer(
                    question_text=label, profile=profile, options=["Yes", "No"],
                    field_id=field_path, answer_lib=answer_lib,
                )
                answer = str(resolution.answer or "").strip().lower()
                if answer not in ("yes", "no"):
                    continue
                button = entry.locator(
                    '.ashby-application-form-input-yesno-option[data-option="' + answer + '"]'
                ).first
                if await button.count() > 0:
                    await button.click(force=True)
                    filled[key] = "Yes" if answer == "yes" else "No"
                    filled_ids[key] = field_path
                    await asyncio.sleep(0.15)
                continue

            if await autocomplete.count() > 0:
                box = autocomplete.first
                if (await box.input_value()).strip():
                    continue
                resolution = resolve_answer(
                    question_text=label, profile=profile, options=None,
                    field_id=field_path, answer_lib=answer_lib,
                )
                answer = str(resolution.answer or "").strip()
                if not answer:
                    continue
                await box.click()
                # Type the city alone: Ashby keys its location list on city, so a
                # full "Seattle, Washington, United States" matches nothing in it.
                head = answer.split(",")[0].strip() or answer
                await box.press_sequentially(head, delay=40)
                options = page.locator('[role="option"]')
                chosen_text = ""
                for _ in range(30):
                    await asyncio.sleep(0.1)
                    texts = await options.evaluate_all(
                        "els => els.map(el => (el.innerText || '').trim())"
                    )
                    if not texts:
                        continue
                    pick = _pick_location_option(texts, answer, profile)
                    if pick is None and texts:
                        for idx, opt_txt in enumerate(texts):
                            opt_low = opt_txt.lower()
                            ans_low = answer.lower()
                            if opt_low == ans_low or ans_low in opt_low or (head.lower() and head.lower() in opt_low):
                                pick = idx
                                break
                    if pick is not None:
                        await options.nth(pick).click(force=True)
                        chosen_text = texts[pick]
                        break
                if chosen_text:
                    filled[key] = chosen_text
                    filled_ids[key] = field_path
                    await asyncio.sleep(0.2)
                continue

            if await radios.count() > 0:
                checked = await radios.evaluate_all("els => els.some(el => el.checked)")
                if checked:
                    continue
                option_texts = await entry.locator("label").evaluate_all(
                    "els => els.slice(1).map(el => (el.innerText || '').trim())"
                )
                option_texts = [t for t in option_texts if t]
                if not option_texts:
                    continue
                resolution = resolve_answer(
                    question_text=label, profile=profile, options=option_texts,
                    field_id=field_path, answer_lib=answer_lib,
                )
                answer = str(resolution.answer or "").strip()
                if not answer:
                    continue
                for offset, text in enumerate(option_texts):
                    if text.strip().lower() == answer.lower():
                        await radios.nth(offset).click(force=True)
                        filled[key] = text
                        filled_ids[key] = field_path
                        await asyncio.sleep(0.15)
                        break
                continue

            checkboxes = entry.locator('input[type="checkbox"]')
            if await yes_no.count() == 0 and await checkboxes.count() > 0 and await text_like.count() == 0:
                # A lone checkbox on an Ashby entry is an acknowledgement or
                # certification ("I hereby certify that ..."). The resolver
                # decides whether it is one the candidate can truthfully tick;
                # anything it declines is left alone for review.
                box = checkboxes.first
                if await box.is_checked():
                    continue
                resolution = resolve_answer(
                    question_text=label, profile=profile, options=["Yes", "No"],
                    field_id=field_path, answer_lib=answer_lib,
                )
                if str(resolution.answer or "").strip().lower() != "yes":
                    continue
                await box.check(force=True)
                filled[key] = "checked"
                filled_ids[key] = field_path
                await asyncio.sleep(0.1)
                continue

            if await text_like.count() > 0:
                box = text_like.first
                if (await box.input_value()).strip():
                    continue
                resolution = resolve_answer(
                    question_text=label, profile=profile, options=None,
                    field_id=field_path, answer_lib=answer_lib,
                )
                answer = str(resolution.answer or "").strip()
                if not answer or resolution.question_type == QuestionType.UNKNOWN.value:
                    continue
                await box.fill(answer)
                # Ashby's inputs are React-controlled, and some of them discard a
                # programmatic value set: observed on "When can you start a new
                # role?", which reported filled but was empty at submit time.
                # Typing raises the same key events a person would, so fall back
                # to that whenever the value did not stick.
                try:
                    if not (await box.input_value()).strip():
                        await box.click()
                        await box.press_sequentially(answer, delay=25)
                except Exception:
                    pass
                # Record what the control actually holds, not what we typed. A
                # date input normalises "2 weeks from offer" into a real date,
                # and recording the phrase instead made the DOM read-back
                # verifier report a mismatch against a field that was filled
                # perfectly well.
                try:
                    settled = (await box.input_value()).strip()
                except Exception:
                    settled = ""
                filled[key] = settled or answer
                filled_ids[key] = field_path
                await asyncio.sleep(0.1)
        except Exception as entry_err:
            logger.debug("Ashby field %s failed: %s", index, entry_err)

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

    Returns (filled, filled_ids) - see _fill_all_greenhouse_comboboxes for why
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
    loc_input = page.locator('input[id*="candidate-location" i], input[id*="candidate_location" i], input[id*="location" i], input[name*="location" i]').first
    if await loc_input.count() > 0 and await loc_input.is_visible():
        city_full = profile.get("location") or "Seattle, WA"
        if city_full.strip().lower() in ("akshay", "akshay borse", "none", ""):
            city_full = "Seattle, WA"
        city_search = (profile.get("city") or city_full.split(",")[0]).strip() or "Seattle"
        try:
            await loc_input.focus()
            await loc_input.press_sequentially(city_search, delay=50)
            filled["Location"] = city_full
            filled_ids["Location"] = await loc_input.get_attribute("id") or ""
            await asyncio.sleep(1.2)
            # Scoped selector for location autocomplete suggestions to avoid matching
            # country or dial-code dropdown menus elsewhere on the page
            suggestions = page.locator(
                '[id*="candidate-location-option"], '
                'div[id*="candidate-location-listbox"] [role="option"], '
                'div[id*="candidate_location"] [role="option"], '
                'div[class*="select__menu"] div[class*="option"], '
                'div[class*="select__option"], '
                '.location-suggestion, .pac-item, li[class*="suggestion"]'
            )
            sug_count = await suggestions.count()
            clicked = False
            if sug_count > 0:
                # Read every suggestion's text in one go, then choose with the
                # same state-aware rule the Ashby pass uses: matching only the
                # city puts "Auburn, Alabama" on the form of a candidate who
                # lives in Auburn, Washington.
                suggestion_texts = await suggestions.evaluate_all(
                    "els => els.map(el => ("
                    "  (el.offsetWidth || el.offsetHeight || el.getClientRects().length)"
                    "    ? (el.innerText || '').trim() : ''"
                    "))"
                )
                pick = _pick_location_option(suggestion_texts, city_full, profile)
                if pick is not None:
                    await suggestions.nth(pick).click(force=True)
                    clicked = True
                    await asyncio.sleep(0.5)
            if not clicked and sug_count == 0:
                # Only blind-select when the widget offered nothing to read. If
                # suggestions existed and none of them was the candidate's town,
                # picking whatever is highlighted is how a wrong city gets onto
                # a real application; leave it empty for review instead.
                try:
                    await _keyboard(page).press("ArrowDown")
                    await asyncio.sleep(0.2)
                    await _keyboard(page).press("Enter")
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            # Record the value the widget actually committed, not the one we
            # set out to type. React-Select clears its text input on selection
            # and renders the choice in a .select__single-value node, so
            # reading input_value() here returns "" and leaves the answers map
            # claiming "Seattle, WA" while the form holds "Seattle, Washington,
            # United States". That bogus mismatch is what sent a correctly
            # filled field into the healing pass, which then re-picked it as a
            # different city entirely.
            try:
                settled = (await loc_input.evaluate("""el => {
                    var wrapper = el.closest('div.select__control, div[class*="select__control"]');
                    var sv = wrapper && wrapper.querySelector('[class*="singleValue"], [class*="single-value"]');
                    return (sv && sv.textContent.trim()) || el.value || '';
                }""") or "").strip()
                if settled:
                    filled["Location"] = settled
            except Exception:
                pass
        except Exception:
            pass

    if log_cb and (filled.get("First Name") or filled.get("Email")):
        log_cb(f"Filled contact info ({first} {last}, {email})")

    # 1b. Ashby forms are label-driven, with Yes/No buttons and an id-less
    # location autocomplete that none of the passes above can reach.
    if await page.locator(".ashby-application-form-field-entry").count() > 0:
        if log_cb:
            log_cb("Filling Ashby application fields...")
        ashby_filled, ashby_ids = await _fill_ashby_fields(page, profile, answer_lib)
        filled.update(ashby_filled)
        filled_ids.update(ashby_ids)

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

    # 3. Structured Employment rows (must precede the combobox pass: ticking
    # "Current role" disables that row's end-date comboboxes).
    emp_filled, emp_ids = await _fill_greenhouse_employment_rows(page, profile, answer_lib)
    filled.update(emp_filled)
    filled_ids.update(emp_ids)

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
                # "Female" ("fe-male") - checking containment before equality
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
    # already detected - never on the first pass - which is why required
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
                # ancestor <div>/<fieldset> - without a label these groups
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
    # every time - this handles fieldset-grouped checkboxes as their own
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
                # case the loop above already owns - not a choice group.
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
                # changes) - this is a React-controlled input that needs its
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

    # Ashby renders a choice question as loose checkboxes with no <fieldset>
    # and no <legend>, so the pass above cannot see it. The only thing tying
    # them together is the question's own uuid, which appears both in the
    # <label for="..."> that holds the real question and inside every
    # checkbox id ("<form>_<question>-labeled-checkbox-<n>"). Each box also
    # carries its option text in `name` rather than in a label.
    #
    # Left undiscovered, these questions were never filled and the
    # pre-submission review reported "0 missing required" - Ramp then rejected
    # the application for a missing required field ("What are your pronouns?")
    # that automation had never even seen.
    try:
        ashby_groups = await page.evaluate(
            """() => {
                const groups = {};
                for (const el of document.querySelectorAll('input[type="checkbox"][id*="-labeled-checkbox-"]')) {
                    if (!(el.offsetParent || el.getClientRects().length)) continue;
                    const m = el.id.match(/^(?:.*_)?(.+?)-labeled-checkbox-\\d+$/);
                    if (!m) continue;
                    const qid = m[1];
                    const labelEl = document.querySelector(`label[for="${CSS.escape(qid)}"]`);
                    if (!labelEl) continue;
                    const own = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    (groups[qid] = groups[qid] || {
                        question: (labelEl.textContent || '').trim(),
                        required: /_required_/.test(labelEl.className || ''),
                        options: [],
                    }).options.push({
                        id: el.id,
                        label: ((own && own.textContent) || el.name || '').trim(),
                        checked: el.checked,
                    });
                }
                return groups;
            }"""
        )
    except Exception as exc:
        logger.debug("Ashby checkbox group discovery error: %s", exc)
        ashby_groups = {}

    for _qid, group in (ashby_groups or {}).items():
        try:
            group_lbl = (group.get("question") or "").strip()
            opts_meta = [o for o in (group.get("options") or []) if o.get("label")]
            if not group_lbl or len(opts_meta) < 2:
                continue
            if any(o.get("checked") for o in opts_meta):
                continue

            options = [o["label"] for o in opts_meta]
            resolution = resolve_answer(
                question_text=group_lbl, profile=profile, options=options,
                answer_lib=answer_lib, field_id=opts_meta[0]["id"],
            )
            if not resolution.answer or resolution.blocking_errors:
                # Nothing in the profile answers this. Leaving it blank is
                # correct - inventing a pronoun or a language is exactly the
                # kind of fabrication this must never do.
                continue

            # "Check all that apply" groups can resolve to several values.
            wanted = [w.strip().lower() for w in str(resolution.answer).split(",") if w.strip()]
            chosen = [
                o for o in opts_meta
                if any(w == o["label"].strip().lower() for w in wanted)
            ] or [
                o for o in opts_meta
                if any(w in o["label"].strip().lower() or o["label"].strip().lower() in w for w in wanted)
            ]
            if not chosen:
                continue

            for opt in chosen:
                target_box = page.locator(f'[id="{opt["id"]}"]').first
                await target_box.evaluate("""el => {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked').set;
                    setter.call(el, true);
                    el.dispatchEvent(new Event('click', { bubbles: true }));
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""")
                if not await target_box.is_checked():
                    label_loc = page.locator(f'label[for="{opt["id"]}"]').first
                    if await label_loc.count() > 0:
                        await label_loc.click(force=True)
                    else:
                        await target_box.check(force=True)

            filled[group_lbl[:50]] = ", ".join(o["label"] for o in chosen)
            filled_ids[group_lbl[:50]] = chosen[0]["id"]
            logger.info("Answered grouped checkbox question %r", group_lbl[:80])
        except Exception as exc:
            logger.debug("Ashby checkbox group fill error: %s", exc)
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

            # Every empty textarea used to be filled with a canned blurb chosen
            # by a substring ladder, defaulting to a generic "extensive
            # production experience..." line when nothing matched. Two things
            # went wrong with that, both observed on real submissions:
            #
            #  * The substring tests are far too loose - "ai" is inside
            #    "expl-ai-n", so "Please explain." selected the AI/LLM blurb and
            #    answered a question about Python backend work, and another
            #    about Flyte/Airflow ETL pipelines, with a claim about LLM
            #    integrations that answered neither.
            #  * The default fired on anything unrecognised, so "What's a topic
            #    or hobby you could present on for 30 minutes?" and, worse, "what
            #    is the basis of your current employment authorization? ... is
            #    there an approved I-140?" both received a tech-stack sentence.
            #
            # A wrong free-text answer on a real application is worse than a
            # blank one: blank gets the job staged for review, where the
            # candidate can answer it themselves. So only answer what the
            # resolver can genuinely ground in the profile, and otherwise leave
            # the field alone.
            essay_res = resolve_answer(
                question_text=ta_lbl.strip(),
                profile=profile,
                options=[],
                answer_lib=answer_lib,
                field_id=ta_id,
            )
            essay_ans = (essay_res.answer or "").strip()
            if not essay_ans or essay_res.confidence < 0.7:
                continue

            await ta.fill(essay_ans)
            # Store the full answer, not a truncated preview - this dict feeds
            # DOM verification later (via form_resolutions), which compares it
            # against the live textarea's full value. A truncated "...' stored
            # here always mismatches the real value, staging every essay-style
            # answer for review even when it was filled correctly.
            filled[ta_lbl[:30] or "Essay"] = essay_ans
            filled_ids[ta_lbl[:30] or "Essay"] = ta_id
        except Exception:
            pass

    # 4. Standard & Custom Text Inputs (LinkedIn, Company, Title, Website, Portfolio)
    # email/tel/number are included because non-Greenhouse boards type their
    # contact fields properly (Ashby uses type="email" and type="tel"), and a
    # text-only selector skipped every one of them.
    text_inputs = await page.locator(
        'input[type="text"], input[type="url"], input[type="email"], input[type="tel"], '
        'input[type="number"], input[type="search"], input:not([type])'
    ).all()
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

            # Ask the centralised resolver first. The if/elif chain below only
            # knows a fixed list of Greenhouse-style labels, so on any other ATS
            # it recognised nothing and the whole form was left blank - Ashby
            # names its custom fields with bare UUIDs ("Preferred FULL Name",
            # "Legal FULL Name", "Mobile Phone", "Location - Zip Code"), which
            # the resolver answers correctly but this pass never asked it about.
            # The chain is kept below purely as a fallback for labels the
            # resolver declines.
            val_to_fill = ""
            resolved_key = ""
            try:
                generic = resolve_answer(
                    question_text=inp_lbl,
                    profile=profile,
                    options=None,
                    field_id=inp_id,
                    answer_lib=answer_lib,
                )
            except Exception:
                generic = None
            if generic is not None and generic.answer and generic.question_type != QuestionType.UNKNOWN.value:
                val_to_fill = str(generic.answer)
                resolved_key = inp_lbl[:50]
                filled[resolved_key] = val_to_fill

            if val_to_fill:
                pass
            elif "linkedin" in inp_lbl_lower:
                val_to_fill = str(profile.get("linkedin") or "")
                filled["LinkedIn"] = val_to_fill
            elif "current company" in inp_lbl_lower or "most recent company" in inp_lbl_lower or "your current company" in inp_lbl_lower or "employer" in inp_lbl_lower:
                val_to_fill = str(profile.get("currentCompany") or "")
                filled["Current Company"] = val_to_fill
            elif "current title" in inp_lbl_lower or "most recent title" in inp_lbl_lower or "your current title" in inp_lbl_lower or "job title" in inp_lbl_lower:
                val_to_fill = str(profile.get("currentTitle") or "")
                filled["Current Title"] = val_to_fill
            elif "state in which you" in inp_lbl_lower or "state of residence" in inp_lbl_lower:
                val_to_fill = str(profile.get("state") or "")
                filled["State"] = val_to_fill
            elif "github" in inp_lbl_lower:
                val_to_fill = str(profile.get("github") or "")
                filled["GitHub"] = val_to_fill
            elif "portfolio" in inp_lbl_lower or "website" in inp_lbl_lower:
                # Never invent a URL here. This previously fell back to a
                # hardcoded "https://amsborse.github.io/resume", which does not
                # exist (404) - real applications went out carrying a dead link
                # as the candidate's portfolio. With no portfolio on the profile
                # the honest substitute is another site the candidate actually
                # has; if there is none, leave the field alone and let the
                # required-field check stage it for review.
                val_to_fill = (
                    str(profile.get("portfolio") or "").strip()
                    or str(profile.get("website") or "").strip()
                    or str(profile.get("github") or "").strip()
                    or str(profile.get("linkedin") or "").strip()
                )
                if val_to_fill:
                    filled["Website"] = val_to_fill

            if val_to_fill:
                await inp.fill(val_to_fill)
                if resolved_key:
                    filled_ids[resolved_key] = inp_id
                for key in ("LinkedIn", "Current Company", "Current Title", "State", "GitHub", "Website"):
                    if filled.get(key) == val_to_fill:
                        filled_ids[key] = inp_id
                await asyncio.sleep(0.1)
        except Exception:
            pass

    return filled, filled_ids


async def _page_has_form_inputs(scope: Any) -> bool:
    """Whether this page actually shows an application form right now.

    Replaces a hostname guess. The only reliable signal that no navigation is
    needed is the presence of real form controls.
    """
    try:
        return await scope.locator(
            'input[type="file"], input[type="email"], input[name*="first_name" i], '
            'input[name="name"], input[autocomplete="given-name"]'
        ).count() > 0
    except Exception:
        return False


async def execute_live_playwright_submission(
    job_item: dict[str, Any],
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
    headless: bool = True,
    timeout_sec: float = 75.0,
    log_callback: Any = None,
    fill_only: bool = False,
    hand_off_seconds: float | None = 0.0,
    on_confirmed: Any = None,
) -> dict[str, Any]:
    """Run the submission on the dedicated Proactor-loop thread (see browser_runner._ensure_playwright_loop).

    Playwright's browser launch spawns a subprocess via asyncio, which raises a bare
    NotImplementedError on Windows if it runs on the ambient (non-Proactor) event loop -
    e.g. uvicorn's own request-handling loop under `--reload` (uvicorn forces
    SelectorEventLoop for its reloaded worker process, see uvicorn/loops/asyncio.py).

    This used to run the impl directly first and only fall back to the dedicated
    Proactor thread on `except NotImplementedError` - but that exception is raised
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
                fill_only=fill_only,
                hand_off_seconds=hand_off_seconds,
                on_confirmed=on_confirmed,
            ),
            # hand_off_seconds=None means the window stays open until the
            # candidate closes it, so there is no deadline to enforce here
            # either - a wall-clock cap is exactly what used to tear the
            # window down while they were still filling the form in.
            timeout=None if hand_off_seconds is None else timeout_sec + hand_off_seconds + 30,
        )

    return await _execute_live_playwright_submission_impl(
        job_item=job_item,
        profile=profile,
        answer_lib=answer_lib,
        headless=headless,
        timeout_sec=timeout_sec,
        log_callback=log_callback,
        fill_only=fill_only,
        hand_off_seconds=hand_off_seconds,
        on_confirmed=on_confirmed,
    )


async def _execute_live_playwright_submission_impl(
    job_item: dict[str, Any],
    profile: dict[str, Any],
    answer_lib: list[dict[str, Any]] | None = None,
    headless: bool = True,
    timeout_sec: float = 75.0,
    log_callback: Any = None,
    fill_only: bool = False,
    hand_off_seconds: float | None = 0.0,
    on_confirmed: Any = None,
) -> dict[str, Any]:
    """Execute autonomous browser submission with strict pre-submit and post-submit verification.

    With ``fill_only`` the run stops once the form is filled and verified and
    never clicks submit. That is how a CAPTCHA-guarded posting is handed over:
    the automation does all the typing, then leaves the window open for
    ``hand_off_seconds`` so the candidate can solve the challenge and press
    submit themselves.
    """
    app_url = job_item.get("applicationUrl") or job_item.get("listingUrl") or ""
    company = job_item.get("company") or "Target Company"
    title = job_item.get("title") or "Target Role"
    job_id = job_item.get("id") or "job"

    # Custom-branded careers domains that embed a Greenhouse job via ?gh_jid=
    # (coupang.jobs, zoominfo.com/careers, samsara.com/company/careers, etc.)
    # render markup our submit-button/field selectors don't recognize -
    # they're built against Greenhouse's own standard form. Redirecting to
    # the canonical job-boards.greenhouse.io URL when we can confidently
    # derive one fixes "Submit button not found" on postings that are
    # genuinely live and Greenhouse-backed, not actually broken.
    if app_url and ("gh_jid=" in app_url.lower() or "greenhouse" in app_url.lower()):
        # Only attempt this when the URL itself already signals Greenhouse
        # involvement - extract_greenhouse_job_ref's job-id fallback pattern
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

    # Per-application Gmail plus-addressing (deterministic reply tracking) -
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
    # discovery scraper sometimes captures instead of the public job page -
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

    # Ashby splits the posting from its form: jobs.ashbyhq.com/<org>/<id> is a
    # description page whose only control is an "Apply for this Job" button, and
    # the form lives at /application. Go straight there rather than relying on
    # finding and clicking that button.
    ashby_match = re.match(
        r"^(https?://jobs\.ashbyhq\.com/[^/]+/[0-9a-fA-F-]{8,})/?$",
        (app_url or "").split("?")[0],
    )
    if ashby_match:
        app_url = f"{ashby_match.group(1)}/application"
        logger.info("Resolved Ashby posting to its application form: %s", app_url)

    resume_file = get_resume_upload_payload(profile)

    # An assisted hand-off gets a persistent profile so the candidate's own
    # autofill builds up across applications; autonomous runs stay on a fresh,
    # throwaway context, because they run unattended and in sequence and must
    # not accumulate or share state between postings.
    use_profile = fill_only and not headless

    async with async_playwright() as p:
        browser: Browser | None = None
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            # Some Greenhouse-hosted boards reset the HTTP/2 connection mid-
            # handshake, which Chromium surfaces as a hard
            # net::ERR_HTTP2_PROTOCOL_ERROR on page.goto and which retrying
            # never clears - observed deterministically on all three Roblox
            # postings, whose URLs load fine over HTTP/1.1. Forcing HTTP/1.1
            # costs a little connection reuse and makes those pages reachable.
            "--disable-http2",
        ]
        # A window a person is going to drive must open maximized, and its page
        # viewport must track the real window (no_viewport below). With a fixed
        # 1280x900 viewport and no window size, Chromium opens a smaller window
        # and renders the page into a surface larger than what is visible, so
        # the bottom of a long application form - the Submit button - sits
        # outside the window and cannot be scrolled to normally.
        if not headless:
            launch_args.append("--start-maximized")

        # Headless runs keep a fixed viewport so form geometry is
        # deterministic; a visible window takes its size from the window
        # itself, which is the only way scrolling behaves for the person
        # who has to finish the form.
        context_opts: dict[str, Any] = {
            "no_viewport": not headless,
            "viewport": None if not headless else {"width": 1280, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        context: BrowserContext
        if use_profile:
            ASSISTED_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            try:
                # channel="chrome" runs the real Chrome rather than the bundled
                # Chromium, so the profile is one Chrome itself can read and the
                # autofill UI behaves the way the candidate expects.
                context = await p.chromium.launch_persistent_context(
                    str(ASSISTED_PROFILE_DIR),
                    channel="chrome",
                    headless=headless,
                    args=launch_args,
                    **context_opts,
                )
                logger.info("Assisted window using the CareerOS Chrome profile at %s", ASSISTED_PROFILE_DIR)
                if log_callback:
                    log_callback(
                        "Opening in your CareerOS Chrome profile — what you fill in here is "
                        "remembered for the next application.",
                    )
            except Exception as profile_err:
                # Chrome missing, or the profile directory already locked by
                # another assisted window. Neither is worth failing the whole
                # hand-off over; fall back to a throwaway context so the user
                # still gets a filled form, just without the saved autofill.
                logger.warning(
                    "Could not open the persistent Chrome profile (%s); falling back to a "
                    "throwaway context.", profile_err,
                )
                if log_callback:
                    log_callback(
                        "Could not open the saved Chrome profile (is another assisted window "
                        "open?) — continuing without your saved autofill.",
                        lvl="warning",
                    )
                browser = await p.chromium.launch(headless=headless, args=launch_args)
                context = await browser.new_context(**context_opts)
        else:
            browser = await p.chromium.launch(headless=headless, args=launch_args)
            context = await browser.new_context(**context_opts)

        # A persistent context opens with a page already in it; reusing that one
        # keeps the window count at one instead of leaving a blank tab behind.
        page: Page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(timeout_sec * 1000)
        # Set once the assisted hand-off loop has actually run, so the teardown
        # below can tell "the person has had their turn with this window" from
        # "we bailed out before they ever saw it".
        handed_off = False

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
            # banner saying the posting closed, instead of redirecting - catch that by text too.
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

            # A pulled posting most reliably announces itself by losing its own
            # identity: we asked for one specific job id and were handed a page
            # that no longer carries it. The path-pattern list above misses the
            # common cross-domain case - a Pinterest posting on
            # job-boards.greenhouse.io redirected to www.pinterestcareers.com/jobs/,
            # whose "/jobs/" segment even matched the list's own exemption, so the
            # run continued and typed the candidate's city into that index page's
            # job-search filter before failing verification on it. Requiring a
            # corroborating signal (the host changed, Greenhouse's own error flag,
            # or a listing-index path) keeps a plain canonical-URL rewrite that
            # still shows the form from being called expired.
            redirect_says_expired = False
            requested_job_id = ""
            id_match = re.search(r"/jobs?/(\d{4,})", (app_url or "").lower()) or re.search(
                r"(?:gh_jid|jobid|job_id)=(\d{4,})", (app_url or "").lower()
            )
            if id_match:
                requested_job_id = id_match.group(1)
            if requested_job_id and requested_job_id not in current_url_lower:
                # Losing the id is necessary but not sufficient: a posting can
                # legitimately hand off to an apply flow on another host whose
                # URL drops the id but still shows a real form. Only a
                # destination that also *looks* like a listing index - a bare
                # /jobs, /careers or /openings, a search page, or Greenhouse's
                # own error=true flag - is treated as a pulled posting.
                try:
                    final_path = urlparse(page.url).path.lower().rstrip("/")
                except Exception:
                    final_path = current_url_lower
                if re.search(r"error=true|[?&]search", current_url_lower) or re.fullmatch(
                    r"(/[a-z0-9._-]+)?(/(jobs|careers|openings|open-roles|search|positions))?", final_path or ""
                ):
                    redirect_says_expired = True

            if url_says_expired or text_says_expired or redirect_says_expired:
                return {
                    "submitted": False,
                    "expired": True,
                    "error": "Job posting has expired or was removed by company (redirected to general career directory)",
                    "evidence": {
                        "finalUrl": page.url,
                    },
                    "fieldsFilled": {},
                }

            # Most of the "other job portals" in the queue - Datadog, Coinbase,
            # Samsara, Zipline, Oscar, Ripple, Block, Fieldwire, Riot - are not
            # separate ATSs at all. They are employer-branded wrappers that embed
            # the real Greenhouse/Lever/Ashby form in a cross-origin iframe, or
            # link out to it from an "Apply now" button (Coinbase does this).
            # Driving that nested frame is what made these postings hang until the
            # 480s watchdog fired: the frame is reachable, but interacting with it
            # through the wrapper stalls.
            #
            # The iframe's own src is authoritative - it carries the correct board
            # slug and validity token, which guessing a slug from the company name
            # cannot reliably reproduce. So navigate the top-level page to it and
            # drive the real form directly.
            # Workable and Lever keep the real form behind an /apply route, and
            # Workable links to it with a RELATIVE href, so a host-only pattern
            # never matched it. A bare /apply suffix is only trusted on the SAME
            # host as the posting: matching it anywhere made an unrelated
            # content.googleapis.com proxy iframe on a Greenhouse page look like
            # an application form.
            try:
                embed_src = await page.evaluate(
                    "() => {"
                    "  const hosted = /greenhouse[.]io|lever[.]co|ashbyhq[.]com|oneclick-ui|workable[.]com/;"
                    "  const here = location.host;"
                    "  const ats = u => { try { return hosted.test(u) || (new URL(u, location.href).host === here && /[/]apply[/]?$/.test(new URL(u, location.href).pathname)); } catch (e) { return false; } };"
                    "  const framed = [...document.querySelectorAll('iframe')]"
                    "    .map(el => el.src || '').find(src => src && ats(src));"
                    "  if (framed) return framed;"
                    "  const links = [...document.querySelectorAll('a[href]')].map(a => a.href || '')"
                    "    .filter(href => href && ats(href));"
                    "  const apply = [...document.querySelectorAll('a[href]')]"
                    "    .filter(a => a.href && ats(a.href) && /apply|interested/i.test(a.textContent || ''));"
                    "  return (apply[0] && apply[0].href) || links[0] || '';"
                    "}"
                )
            except Exception:
                embed_src = ""
            # SmartRecruiters hides its form behind an "I'm interested" link to a
            # oneclick-ui page, so the posting URL itself never has one.
            #
            # Being ON the ATS host is not the same as being ON its form.
            # Greenhouse renders the form inline on the posting URL, but Lever
            # and Workable serve a job DESCRIPTION there and keep the form at
            # /apply. Short-circuiting on the hostname meant the /apply URL this
            # code had just resolved was thrown away, the description page had
            # zero inputs, and the run died as "No application form on the
            # posting page" - on boards whose forms are perfectly fillable.
            # Verified live: jobs.lever.co/<co>/<id>/apply exposes 15 text
            # inputs and a file input with no bot wall.
            on_form_already = await _page_has_form_inputs(page)
            already_on_ats = on_form_already or "oneclick-ui" in page.url
            # Greenhouse's /embed/job_app endpoint only works while it is framed
            # by the employer's page. Opened as a top-level document it returns a
            # stub: a few inputs and NO submit control at all. Measured on two
            # postings, in-frame vs. the identical URL standalone:
            #
            #   Databricks  47 inputs + "Submit application"  ->  3 inputs, none
            #   Datadog     26 inputs + "Submit application"  ->  1 input,  none
            #
            # So navigating to it throws away the real form. An autonomous run
            # then reports "Application form and submit button not found" (that
            # is the Datadog failure), and an assisted hand-off leaves the
            # candidate staring at a form with no Apply button - reported live on
            # the Databricks posting.
            #
            # The iframe switch immediately below reaches the very same form from
            # the employer's page, so there is nothing to gain by leaving it.
            # Standalone ATS URLs (jobs.lever.co/.../apply, a real Greenhouse
            # job page, Ashby application URLs) are unaffected: they are proper
            # top-level pages and are still followed.
            if embed_src and "/embed/job_app" in embed_src:
                logger.info(
                    "Not following %s: Greenhouse's embed endpoint only renders a "
                    "submittable form while framed. Staying on %s and driving the "
                    "form through its iframe instead.",
                    embed_src, page.url,
                )
                if log_callback:
                    log_callback(
                        "Staying on the employer's page — its embedded form only works there.",
                    )
                embed_src = ""

            if embed_src and not already_on_ats:
                logger.info("Employer page points at an ATS form; navigating directly to %s", embed_src)
                if log_callback:
                    log_callback("Following embedded application form to its ATS host...")
                try:
                    await asyncio.wait_for(
                        page.goto(embed_src, wait_until="domcontentloaded", timeout=45000),
                        timeout=50.0,
                    )
                    await asyncio.sleep(2.0)
                except Exception as embed_err:
                    logger.warning("Could not open embedded form %s: %s", embed_src, embed_err)

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

            # Dismiss any cookie / GDPR consent overlays immediately so inputs and frames are reachable
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
                        await consent_btn.click(timeout=1500)
                        await asyncio.sleep(0.3)
                        break
                except Exception:
                    pass

            # If application form is not yet visible, check for matching job links or "Apply" buttons
            # A bare `form` element is not evidence of an application form: every
            # careers page has a site-search form, and matching it meant the
            # "Apply" button below never got clicked on a job-description page.
            # Look for inputs only a real application has.
            #
            # A bare file input is NOT enough evidence either: Microsoft's job
            # description page (apply.careers.microsoft.com) has a standalone
            # "Upload your resume" quick-upload widget with nothing else on it,
            # which satisfied `input[type="file"]` alone and made every attempt
            # skip the Apply-link click below, permanently stalling on the
            # description page ("Submit button not found") no matter what the
            # click selectors further down could match. A real application form
            # reliably has at least one identity field (name/email/candidate);
            # a lone upload widget does not.
            APPLICATION_FORM_SELECTOR = (
                '#first_name, #email, input[id*="first_name" i], '
                'input[name*="first_name" i], input[name*="last_name" i], '
                'input[autocomplete="given-name"], input[id*="candidate" i]'
            )
            try:
                # Checked live against Microsoft's page: a bare file-input +
                # single-text-input fallback was tried here and immediately
                # false-positived too (the page header's job search box is
                # itself one text input), so identity fields are the only
                # reliable signal - no fallback.
                form_present = await target_frame.locator(APPLICATION_FORM_SELECTOR).count() > 0
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
                        # Microsoft's careers site (apply.careers.microsoft.com)
                        # renders "Apply now" as an <a> whose visible label is
                        # not exposed as matchable text content (a custom-
                        # rendered/ARIA-managed label), so every :has-text()
                        # selector above silently misses it and the run stalls
                        # on the job-description page with no form. The link
                        # target itself is stable and site-specific.
                        'a[href*="/careers/apply?"]',
                        # Apple's careers site (jobs.apple.com) labels its link
                        # "Submit Resume" rather than "Apply" at all, so no
                        # text-based selector above ever matches it. The href
                        # itself is a stable "/apply/<job id>" pattern, and
                        # this generic form (rather than Apple's exact path)
                        # also covers other ATS/career sites using the same
                        # "/apply/" URL convention with non-"Apply" wording.
                        'a:has-text("Submit Resume")',
                        'a[href*="/apply/"]',
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

            # Client-rendered application forms (Ashby, Lever, SmartRecruiters)
            # mount their inputs after an async fetch, so a fixed sleep after
            # navigation is a race. Observed on Ashby: field discovery ran
            # against an empty page, the deterministic review declared "0 missing
            # required" because it had found no fields at all, and the run went
            # on to click Submit on a form nothing had filled. Wait for real
            # inputs to exist before reading the form.
            for _ in range(30):
                try:
                    ready = await target_frame.locator(
                        'input[type="text"], input[type="email"], input[type="tel"], textarea'
                    ).count()
                except Exception:
                    ready = 0
                if ready:
                    break
                await asyncio.sleep(0.5)

            # Some postings render only a job description at the application URL
            # (observed on Pinterest and Brex links that live on greenhouse.io but
            # hand the actual apply flow to the employer's own site). Filling a
            # page that has no application form does not fail - it stalls, and the
            # job burned the full 480s watchdog before being marked FAILED with a
            # timeout that says nothing about the real cause. Detect it here and
            # say so immediately.
            # ── Workday: get past the chooser before deciding there is no form ──
            #
            # A Workday posting's /apply URL is not a form at all. It is a menu -
            # "Autofill with Resume", "Apply Manually", "Use My Last Application" -
            # with zero inputs on it, so the check below concluded "no application
            # form on the posting page" and gave up on a perfectly live posting.
            # Verified on Blue Origin's tenant.
            #
            # Choosing "Apply Manually" advances to step 1 of 8, which is
            # Create Account / Sign In. That account is a hard gate: the seven
            # steps that hold the actual application are behind it, and creating
            # it (or typing a password) is not something this automation does.
            # So the goal here is narrow and honest - drive the posting as far as
            # it legitimately can go, then say precisely what is blocking it.
            if "myworkdayjobs.com" in (page.url or "").lower():
                workday_state = await _advance_workday_to_form(page, log_callback)
                if workday_state == "needs_account":
                    reason = (
                        "Workday requires a candidate account on this employer's tenant, and "
                        "the application form is behind that sign-in. Sign in once in this "
                        "window and the account is remembered for next time."
                    )
                    if fill_only:
                        # The window is handed over below by the teardown path;
                        # the candidate signs in and completes the wizard.
                        if log_callback:
                            log_callback(reason, lvl="warning")
                    else:
                        return {
                            "submitted": False,
                            "error": reason,
                            "evidence": {"atsPlatform": "workday", "workdayStep": "sign-in"},
                            "fieldsFilled": {},
                        }
                # "form" falls through to the normal filling path below: the
                # profile is already signed in and the wizard is reachable.

            try:
                has_form = await target_frame.locator(APPLICATION_FORM_SELECTOR).count() > 0
            except Exception:
                has_form = True  # never block a submission on a probe that errored
            if not has_form:
                # A page with no form may simply be a job description, or it may
                # be a form that never rendered because a bot challenge is
                # standing in front of it - SmartRecruiters' apply flow serves a
                # DataDome captcha and an otherwise empty document. Those are
                # very different outcomes for the user: one is a dead end, the
                # other is a posting they can finish by hand.
                try:
                    wall = await page.evaluate(
                        "() => { const s = [...document.querySelectorAll('iframe')].map(f => f.src || '').join(' '); "
                        "if (/captcha-delivery|datadome/i.test(s)) return 'DataDome'; "
                        "if (/recaptcha/i.test(s)) return 'reCAPTCHA'; "
                        "if (/turnstile/i.test(s)) return 'Cloudflare Turnstile'; "
                        "if (/hcaptcha/i.test(s)) return 'hCaptcha'; "
                        "return ''; }"
                    )
                except Exception:
                    wall = ""
                if wall:
                    logger.warning("%s bot protection is blocking the form at %s", wall, page.url)
                    return {
                        "submitted": False,
                        "error": (
                            f"{wall} bot protection on this board blocked the application form - "
                            "this posting has to be completed by hand"
                        ),
                        "evidence": {"finalUrl": page.url},
                        "fieldsFilled": {},
                    }
                logger.warning("No application form found at %s - nothing to fill", page.url)
                return {
                    "submitted": False,
                    "error": (
                        "No application form on the posting page - this employer's apply flow "
                        "starts elsewhere and cannot be driven from this URL"
                    ),
                    "evidence": {"finalUrl": page.url},
                    "fieldsFilled": {},
                }

            # ─── DISCOVER & PERSIST FIELDS BEFORE RESOLUTION ─────────────────
            try:
                # Discovery opens each custom dropdown so the resolver sees its
                # real options. The later verification pass deliberately does
                # not - it reads what was filled and must not touch the form.
                discovered_dom_fields, _ = await _extract_dom_form_state(target_frame, expand_comboboxes=True)
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

                # A choice group whose requiredness the DOM never states (see
                # requirednessUnknown in _extract_dom_form_state) cannot be
                # waved through just because nothing marked it required. An
                # entirely unanswered question is not a verified form, so it
                # goes to the healing round that already resolves questions
                # from the profile - and, failing that, stages for review
                # instead of being submitted into a validation error.
                unanswered_unknown = [
                    f for f in dom_fields
                    if f.get("requirednessUnknown")
                    and not f.get("value")
                    and not _is_voluntary_disclosure(f.get("label", ""))
                ]
                if unanswered_unknown:
                    logger.info(
                        "Pre-submission audit: %d unanswered question(s) with no requiredness "
                        "signal in the DOM — routing to healing rather than fast-approving: %s",
                        len(unanswered_unknown),
                        [f.get("label", "")[:60] for f in unanswered_unknown][:5],
                    )

                if not validation_errors and not missing_req and not unanswered_unknown:
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
                    # "candidate-location" - a different field entirely - for
                    # what it meant as the fix for a hybrid-work Yes/No
                    # question). Blindly trusting fieldId then writes the fix
                    # value into a completely unrelated field (observed live: a
                    # "Yes" fix landing in the Location autocomplete while the
                    # actual target question stayed empty). Cross-check the
                    # LLM's claimed label against that id's real DOM label
                    # before applying anything - if they share no meaningful
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
                    #
                    # Always ask the resolver, even when the review already
                    # suggested a value. A fact the profile states outright is
                    # not the LLM's to revise: Discord asks "Are you currently
                    # based in or willing to relocate to the Bay Area for this
                    # position?", the profile says the candidate is willing, and
                    # the review's "No" was submitted over it — an answer the
                    # candidate never gave, on a question that decides the
                    # application.
                    heal_resolution = resolve_answer(
                        question_text=f_label,
                        profile=profile,
                        answer_lib=answer_lib,
                    )
                    if heal_resolution.answer and heal_resolution.resolution_method == PROFILE_EXACT:
                        if fix_val and str(fix_val).strip() != str(heal_resolution.answer).strip():
                            logger.warning(
                                "Review suggested %r for %r; using the profile's %r instead",
                                str(fix_val)[:40], f_label[:60], str(heal_resolution.answer)[:40],
                            )
                        fix_val = heal_resolution.answer
                    elif not fix_val:
                        fix_val = heal_resolution.answer

                    # A prose box wants prose. Both the LLM's suggested fix and
                    # the resolver will happily hand back a one-word answer for
                    # a question whose text merely starts like a Yes/No, and it
                    # gets typed in verbatim: "What is your experience with
                    # backend development in a team production environment
                    # using Python? Please explain." was submitted answering
                    # "Yes", and "Have you recently worked at a FinTech or
                    # FinServ company? If yes, please state where." answering
                    # "Washington". Dropping the token here lets the generator
                    # below write a real answer, or sends the job to review.
                    if fix_val and _is_token_answer_in_prose_box(
                        dom_fields_by_id.get(f_id or ""), f_label, fix_val
                    ):
                        logger.info(
                            "Discarding token answer %r for the prose question %r",
                            str(fix_val)[:40], f_label[:70],
                        )
                        fix_val = ""

                    # Open-ended questions have no profile field to resolve from.
                    #
                    # "Why do you want to work at X?" is not a fact the profile
                    # holds, so the resolver correctly returns nothing - and the
                    # application then stalls on a required field it could
                    # otherwise have answered. This was the single most common
                    # recoverable stop: three of four non-submissions in one
                    # batch were exactly this question at different employers.
                    #
                    # generate_theory_answer writes from the candidate's own
                    # resume and profile under an explicit no-invention rule, so
                    # the answer is the candidate's real evidence in prose. If
                    # it cannot produce one, the field stays empty and the
                    # application still goes to review rather than being sent
                    # with something made up.
                    if not fix_val and _is_open_ended_question(dom_fields_by_id.get(f_id or ""), f_label):
                        try:
                            from app.services.application_assistant.llm_answer_generator import (
                                generate_theory_answer,
                            )

                            generated = await generate_theory_answer(
                                f_label,
                                company=company,
                                role=title,
                                profile=profile,
                                settings=await _load_settings_for_generation(),
                            )
                            if generated.get("success") and generated.get("answer"):
                                fix_val = str(generated["answer"]).strip()
                                logger.info(
                                    "Generated an answer for the open question %r (%d chars)",
                                    f_label[:60], len(fix_val),
                                )
                                if log_callback:
                                    log_callback(
                                        f"Wrote an answer for \"{f_label[:58]}\" from your own experience.",
                                    )
                        except Exception:
                            logger.exception("Could not generate an answer for %r", f_label[:60])
                    if f_id:
                        elem = target_frame.locator(f'[id="{f_id}"]').first
                        if await elem.count() > 0:
                            try:
                                is_cb = False
                                # One evaluate, not four, and with a short explicit
                                # timeout. Locator.evaluate auto-waits for the element
                                # to be attached, so four separate calls against a
                                # field that the form has since re-rendered away burned
                                # 4 x the default timeout - for two such fields that is
                                # the entire 480s submission watchdog, which is exactly
                                # how the Coinbase and Samsara runs died without ever
                                # reaching the submit click.
                                probe = await elem.evaluate(
                                    "el => ({"
                                    "  type: (el.type || el.getAttribute('type') || '').toLowerCase(),"
                                    "  tag: (el.tagName || '').toLowerCase(),"
                                    "  role: (el.getAttribute('role') || '').toLowerCase(),"
                                    "  cls: (typeof el.className === 'string' ? el.className : '').toLowerCase()"
                                    "})",
                                    timeout=5000,
                                )
                                el_type = probe.get("type") or ""
                                tag_name = probe.get("tag") or ""
                                role = probe.get("role") or ""
                                cls = probe.get("cls") or ""
                                if role == "combobox" or "select__control" in cls:
                                    is_cb = True
                                if tag_name in ("div", "fieldset", "section") and not is_cb and el_type not in ("file", "checkbox"):
                                    inner_cb = elem.locator('div.select__control, div[class*="control"], [role="combobox"]').first
                                    inner_radio = elem.locator('input[type="radio"]').first
                                    inner_sel = elem.locator('select').first
                                    if await inner_cb.count() > 0:
                                        is_cb = True
                                    elif await inner_radio.count() > 0:
                                        el_type = "radio"
                                    elif await inner_sel.count() > 0:
                                        el_type = "select"

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
                                        # clicked, not the guessed fix_val - it can decline
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
                                elif el_type == "select":
                                    inner_sel = elem if tag_name == "select" else elem.locator("select").first
                                    if await inner_sel.count() > 0 and fix_val:
                                        opt_data = await inner_sel.evaluate("sel => Array.from(sel.options).map(o => ({ value: o.value, text: o.text }))")
                                        clean_f = str(fix_val).strip().lower()
                                        for opt in opt_data:
                                            if clean_f and (opt["text"].strip().lower() == clean_f or opt["value"].strip().lower() == clean_f):
                                                await inner_sel.select_option(value=opt["value"])
                                                filled_fields[f_label or f_id] = opt["text"]
                                                filled_field_ids[f_label or f_id] = f_id
                                                if log_callback:
                                                    log_callback(f"Self-healed [{f_label or f_id}] -> '{opt['text']}'")
                                                break
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
                                    # Native <select> elements don't support .fill() - Playwright raises on
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
            # classification for cross-field validation below - NOT to
            # re-derive the answer. It's called with no `options` (the actual
            # live dropdown/radio options aren't available anymore at this
            # point), so for a Yes/No-style question it can classify and
            # resolve differently than the original fill-time call did (which
            # saw the real options) and return a different answer entirely.
            # Verification then compares that fresh, options-blind guess
            # against the live DOM value under the field's own label - an
            # unrelated field can share enough of that label as a substring to
            # get matched, so a wrong guess here surfaces as a nonsensical
            # mismatch on a completely different question (observed live: a
            # location answer flagged as conflicting with an office-days
            # Yes/No field's selected value). The fix is field_id: every fill
            # site above now records the live DOM element id it actually
            # wrote into (filled_field_ids), so verification can pair each
            # resolution back to its own element by id instead of by fuzzy
            # label/substring matching. The answer itself is also overwritten
            # with `ans` - the real value this function wrote into the DOM -
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

            # 6a. Assisted hand-off: everything is typed in, and the human takes
            # it from here. This is what makes a CAPTCHA-guarded board worth
            # keeping - the candidate solves the one thing automation must not,
            # instead of re-typing the whole form. The submit click is never
            # made here, whatever the policy gates say.
            if fill_only:
                # Leave the window showing the button the candidate needs.
                #
                # A filled Greenhouse application is a very long document - the
                # Robinhood posting measures 6178px against a 900px viewport -
                # and "Submit application" sits at the very bottom. Handing the
                # window over at whatever scroll position the last field write
                # happened to leave shows the middle of a form with no visible
                # way to send it, which reads as a broken page. The button is
                # there; it is simply thousands of pixels below the fold.
                # Ordered, not a set: the form frame is where the real submit
                # control lives, and a set would search them in arbitrary order.
                frames_to_search = [target_frame]
                if page is not target_frame:
                    frames_to_search.append(page)
                for frame in frames_to_search:
                    try:
                        submit = frame.locator(
                            'button[type="submit"], input[type="submit"], '
                            'button:has-text("Submit application"), button:has-text("Submit")'
                        ).last
                        if await submit.count() > 0:
                            await submit.scroll_into_view_if_needed(timeout=4000)
                            if log_callback:
                                log_callback("Scrolled the window to the Submit button — press it when you are ready.")
                            break
                    except Exception:
                        continue
                else:
                    try:
                        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    except Exception:
                        pass

                hand_off_shot = SCREENSHOTS_DIR / f"{job_id}_assisted.png"
                try:
                    await page.screenshot(path=str(hand_off_shot), full_page=True, timeout=5000)
                except Exception:
                    pass
                logger.info(
                    "Assisted fill complete for %s - %d field(s) filled; handing over for %.0fs",
                    company, len(filled_fields), hand_off_seconds,
                )
                if log_callback:
                    log_callback(
                        f"Filled {len(filled_fields)} field(s) on the {company} form. "
                        "Solve any challenge and press Submit in the open browser window.",
                    )
                # Watch the handed-over window. If the candidate submits it
                # themselves, the ATS says so - and the job should mark itself
                # submitted rather than making them come back and click
                # "Mark submitted" for something they already did.
                handed_off = True
                confirmed_by_user = ""
                # `None` means wait for as long as the window is open. A
                # wall-clock deadline here closed the browser out from under
                # the candidate mid-application - the one thing an assisted
                # hand-off must never do, since the whole point is that a
                # person finishes the form at their own pace. The window
                # closing is the real end signal, so that is what is waited on.
                if hand_off_seconds is None or hand_off_seconds > 0:
                    deadline = (
                        None
                        if hand_off_seconds is None
                        else asyncio.get_running_loop().time() + hand_off_seconds
                    )
                    while deadline is None or asyncio.get_running_loop().time() < deadline:
                        if page.is_closed():
                            break
                        try:
                            current = page.url or ""
                            if not confirmed_by_user:
                                if "confirmation" in current.lower() or "thank" in current.lower():
                                    confirmed_by_user = current
                                else:
                                    body_text = (
                                        await page.locator("body").inner_text(timeout=2000)
                                    ).lower()
                                    if re.search(
                                        r"application (was |has been )?(successfully )?(submitted|received)"
                                        r"|thank you for applying|thanks for applying",
                                        body_text,
                                    ):
                                        confirmed_by_user = current or "confirmation text on page"
                                if confirmed_by_user:
                                    if log_callback:
                                        log_callback(
                                            f"Saw a confirmation on the {company} form. Recording it "
                                            "now; the window stays open until you close it.",
                                        )
                                    # Record it the moment it is seen.
                                    #
                                    # Keeping the window open, so the candidate
                                    # is not thrown out of their own
                                    # application, must not also delay the
                                    # bookkeeping: waiting for the window to
                                    # close meant a submission they had just
                                    # made still showed as unsubmitted in the
                                    # app. Detection and persistence are
                                    # separate concerns and now happen
                                    # separately.
                                    if on_confirmed is not None:
                                        try:
                                            await on_confirmed({
                                                "confirmationUrl": confirmed_by_user,
                                                "fieldsFilled": filled_fields,
                                            })
                                        except Exception:
                                            logger.exception(
                                                "Could not record the assisted submission for %s", company,
                                            )
                        except Exception:
                            pass
                        await asyncio.sleep(1.5)

                if confirmed_by_user:
                    logger.info("Assisted hand-off confirmed by the candidate for %s", company)
                    if log_callback:
                        log_callback(f"You submitted the {company} application - marking it submitted.")
                    return {
                        "submitted": True,
                        "assisted": True,
                        "submissionSource": "manual-assisted",
                        "evidence": {
                            "confirmationText": "Confirmed on screen after assisted hand-off",
                            "confirmationUrl": confirmed_by_user,
                            "assistedScreenshotPath": str(hand_off_shot.resolve()) if hand_off_shot.exists() else "",
                        },
                        "fieldsFilled": filled_fields,
                    }

                return {
                    "submitted": False,
                    "assisted": True,
                    "status": "MANUAL_REVIEW",
                    "error": "",
                    "evidence": {
                        "assistedScreenshotPath": str(hand_off_shot.resolve()) if hand_off_shot.exists() else "",
                        "domVerification": dom_verification.to_dict(),
                    },
                    "fieldsFilled": filled_fields,
                }

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
            # careers page, a CookieYes-style ".cky-overlay") - dismiss it
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
                        # application form's - observed live: it grabbed a
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
                # had an application form to begin with - observed live on two
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
                        "No application form on the page - the posting appears to be closed or "
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
                    # Explicitly generous: this call site's own 45s ceiling was
                    # what stranded submissions whose code email took longer to
                    # show up in Gmail than that. Still well inside the 480s
                    # per-job watchdog in autopilot_runner.
                    timeout_sec=150.0,
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
            # Same lesson as the verification flow's own 150s timeout above, one
            # stage later: Block's real "Thank you for applying" confirmation
            # (from no-reply@block.xyz, separate from Greenhouse's code email)
            # arrived 41-44s after the code-verification round trip completed -
            # inside the old 45s ceiling on a good run, but not with any margin.
            # Two consecutive Block jobs timed out here, got marked FAILED with
            # "no confirmation page or confirmation message was detected", and
            # both had a real ATS confirmation email waiting in Gmail minutes
            # later - a false negative on an application that had already gone
            # through.
            max_wait_sec = 90.0
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
                # A form that stays on screen after a clean submit click is the
                # signature of bot protection refusing the post. Only look for it
                # here, after a real failure: plenty of boards that submit fine
                # also embed an invisible reCAPTCHA, so presence alone must never
                # block a board that works. Naming it turns an opaque "submit
                # button is still active" into a reason that classifies as
                # BOT_PROTECTED_BOARD and stops the job being retried forever.
                try:
                    bot_wall = await target_frame.evaluate(
                        "() => { const srcs = [...document.querySelectorAll('iframe')].map(f => f.src || '').join(' '); "
                        "const html = document.documentElement.innerHTML; "
                        "if (/recaptcha/i.test(srcs) || /g-recaptcha|grecaptcha/i.test(html)) return 'reCAPTCHA'; "
                        "if (/turnstile/i.test(srcs) || /cf-turnstile/i.test(html)) return 'Cloudflare Turnstile'; "
                        "if (/hcaptcha/i.test(srcs) || /h-captcha/i.test(html)) return 'hCaptcha'; "
                        "return ''; }"
                    )
                except Exception:
                    bot_wall = ""
                # A form still on screen because it is asking for the emailed
                # security code is not a board refusing automation - it is the
                # normal Greenhouse flow, one step from done. Blaming the
                # reCAPTCHA that every Greenhouse page embeds sent a perfectly
                # submittable application to manual review with a reason that
                # was simply untrue. Check for the code prompt first and say
                # what is actually outstanding.
                awaiting_code = False
                try:
                    body_low = (body_text or "").lower()
                    awaiting_code = (
                        "verification code was sent to" in body_low
                        or "enter the 8-character code" in body_low
                        or "security code" in body_low
                    )
                except Exception:
                    awaiting_code = False

                if awaiting_code:
                    err_msg = (
                        "The application was filled and submitted, but Greenhouse's emailed "
                        "security code was never entered, so it is still waiting on that step"
                    )
                elif bot_wall and form_still_visible:
                    err_msg = (
                        f"{bot_wall} bot protection on this board blocked the submission - "
                        "this posting has to be completed by hand"
                    )
                is_staged = bool(active_errors) or "missing entry for required field" in err_msg.lower() or "active validation errors" in err_msg.lower()
                logger.error("Submission unconfirmed by Qwen verification: %s", err_msg)
                return {
                    "submitted": False,
                    "stagedForReview": is_staged,
                    "status": "NEEDS_REVIEW" if is_staged else "FAILED",
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
            # An assisted run must hand its window over no matter what the
            # automation concluded, and every bucket gets the same treatment.
            #
            # The hand-off loop lives deep inside the happy path, so every early
            # return above it - a bot wall, a page with no form, a navigation
            # error - fell straight through to this teardown and the window the
            # user had just asked for vanished as soon as it appeared. Reported
            # live on a ZoomInfo posting, and it is worst exactly where assisted
            # fill matters most: a board behind a CAPTCHA is the case where only
            # a human can finish, and closing the window is what stops them.
            #
            # Whatever happened, if the person is expecting a window, they get
            # one, and it stays until they close it.
            if fill_only and not handed_off and not page.is_closed():
                logger.info(
                    "Assisted run ended early (%s) but the window stays open for the "
                    "candidate to finish by hand.", company,
                )
                if log_callback:
                    log_callback(
                        "Automation could not complete this form. The window is yours — "
                        "finish it and submit there; it stays open until you close it.",
                    )
                try:
                    while not page.is_closed():
                        await asyncio.sleep(1.5)
                except Exception:
                    pass
            await context.close()
            # A persistent context owns its browser process, so there is no
            # separate Browser handle to close in that case.
            if browser is not None:
                await browser.close()
