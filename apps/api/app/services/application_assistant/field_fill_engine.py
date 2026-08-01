"""Generic DOM-aware field fill engine — strategy is chosen at fill time from live page state."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from app.services.application_assistant.answer_classification import (
    infer_phone_country,
    is_phone_country_field,
)
from app.services.application_assistant.css_selectors import normalize_css_selector

FILL_SKIP = "skip"
FILL_NATIVE_SELECT = "native_select"
FILL_CUSTOM_SELECT = "custom_select"
FILL_PHONE_COUNTRY = "phone_country"
FILL_TEXT = "text"
FILL_CHECKBOX = "checkbox"
FILL_FILE = "file"

# Cap how many visible dropdown options fast replay scans (Greenhouse keeps many menus in the DOM).
_FAST_OPTION_SCAN_LIMIT = 60
_REPLAY_FIELD_TIMEOUT_SEC = 12.0
_REPLAY_SELECT_TIMEOUT_SEC = 22.0


def _guess_mime_type(file_name: str) -> str:
    lower = file_name.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".doc"):
        return "application/msword"
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"


async def _set_input_file(el: Any, file_path: str, *, file_name: str = "") -> None:
    """Upload a file using the original resume/document filename when possible."""
    path = Path(file_path)
    display_name = (file_name or path.name).strip() or path.name
    await el.set_input_files(
        {
            "name": display_name,
            "mimeType": _guess_mime_type(display_name),
            "buffer": path.read_bytes(),
        }
    )


_DOM_ANALYSIS_JS = """(el) => {
    if (!el) return { missing: true };
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const id = el.id || '';
    const cls = el.className || '';
    const field = el.closest('.field, .application-question, .question, li.application-question, .demographic_question, .field-wrapper');
    return {
        tag,
        type,
        role,
        id,
        cls,
        ariaHaspopup: (el.getAttribute('aria-haspopup') || '').toLowerCase(),
        readOnly: !!el.readOnly,
        hidden: type === 'hidden' || el.hidden || style.display === 'none' || style.visibility === 'hidden',
        visible: !!(el.offsetParent || tag === 'select' || role === 'combobox'),
        sizeZero: rect.width <= 1 && rect.height <= 1,
        inIti: !!el.closest('.iti'),
        itiSearch: cls.includes('iti__search-input') || (id.includes('iti') && id.includes('search')),
        itiCountry: !!el.closest('.iti') && (id === 'country' || el.getAttribute('name') === 'country'),
        inCustomSelect: !!el.closest('.select-shell, .select__container, .select__control'),
        fieldHasCombobox: !!field?.querySelector('[role="combobox"], .select__control, .select-shell'),
    };
}"""

_FIELD_ROOT_JS = """(label) => {
    const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const target = norm(label).slice(0, 80);
    if (!target) return null;
    const candidates = document.querySelectorAll('.field, .application-question, .question, li.application-question, .demographic_question, .field-wrapper, label');
    for (const node of candidates) {
        const text = norm(node.textContent || node.innerText || '');
        if (!text.includes(target.slice(0, 40))) continue;
        const root = node.closest('.field, .application-question, .question, li.application-question, .demographic_question, .field-wrapper') || node.parentElement;
        if (root) return root;
    }
    return null;
}"""

_CONTROL_IN_ROOT_JS = """(root) => {
    if (!root) return null;
    const pick = (sel) => root.querySelector(sel);
    return pick('[role="combobox"]')
        || pick('.select__control')
        || pick('.select-shell input')
        || pick('select')
        || pick('textarea')
        || pick('input:not([type="hidden"]):not([type="submit"])');
}"""


_CONTROL_SELECTOR_JS = """(el) => {
    const field = el.closest('.field, .application-question, .question, li.application-question, .demographic_question, .field-wrapper');
    const control = field?.querySelector(
        '[role="combobox"], .select__control, .select-shell input, button[aria-haspopup="listbox"]'
    ) || (el.getAttribute('role') === 'combobox' ? el : null);
    if (!control) return '';
    if (control.id) return `#${control.id}`;
    const name = control.getAttribute('name');
    if (name) return `[name="${name}"]`;
    return '';
}"""


def is_custom_select_meta(meta: dict[str, Any]) -> bool:
    """True when live DOM metadata indicates a custom/React-Select dropdown."""
    if meta.get("missing") or meta.get("tag") == "select":
        return False
    return bool(
        meta.get("role") == "combobox"
        or meta.get("ariaHaspopup") in ("listbox", "true")
        or meta.get("inCustomSelect")
        or meta.get("fieldHasCombobox")
        or (meta.get("readOnly") and meta.get("tag") == "input")
    )


async def is_custom_select_element(el: Any) -> bool:
    return is_custom_select_meta(await _analyze_element(el))


async def resolve_custom_select_selector(page: Any, el: Any) -> str:
    """Prefer the visible combobox control over hidden/react-select inputs."""
    try:
        resolved = await el.evaluate(_CONTROL_SELECTOR_JS)
        return str(resolved or "")
    except Exception:
        return ""


def _field_meta(field: dict[str, Any]) -> dict[str, str]:
    raw_selector = str(field.get("selector") or field.get("selectorHint") or "")
    return {
        "label": str(field.get("fieldLabel") or field.get("label") or ""),
        "selector": normalize_css_selector(raw_selector),
        "fieldType": str(field.get("fieldType") or field.get("type") or "").lower(),
        "fieldId": str(field.get("fieldId") or field.get("id") or ""),
        "name": str(field.get("name") or ""),
    }


def choose_fill_strategy(meta: dict[str, Any], *, profile: dict[str, Any] | None = None) -> str:
    """Pure strategy selection from DOM metadata."""
    if meta.get("missing"):
        return FILL_SKIP
    if meta.get("itiSearch") or (meta.get("inIti") and meta.get("type") == "search"):
        return FILL_SKIP
    if meta.get("type") == "file":
        return FILL_FILE
    if meta.get("hidden") or meta.get("sizeZero") or not meta.get("visible"):
        return FILL_SKIP
    if meta.get("itiCountry"):
        return FILL_PHONE_COUNTRY
    if meta.get("tag") == "select":
        return FILL_NATIVE_SELECT
    if meta.get("type") in ("checkbox", "radio"):
        return FILL_CHECKBOX
    if (
        meta.get("role") == "combobox"
        or meta.get("ariaHaspopup") in ("listbox", "true")
        or meta.get("inCustomSelect")
        or meta.get("fieldHasCombobox")
        or (meta.get("readOnly") and meta.get("tag") == "input")
    ):
        return FILL_CUSTOM_SELECT
    if meta.get("tag") in ("input", "textarea"):
        return FILL_TEXT
    return FILL_SKIP


async def _analyze_element(el: Any) -> dict[str, Any]:
    try:
        return await el.evaluate(_DOM_ANALYSIS_JS)
    except Exception:
        return {"missing": True}


async def _resolve_element(page: Any, field: dict[str, Any], *, fast_mode: bool = False) -> Any | None:
    """Find the best element to interact with: visible selector first, then label-anchored control."""
    meta = _field_meta(field)
    selector = meta["selector"]
    label = meta["label"]

    if selector:
        try:
            el = await page.query_selector(selector)
        except Exception:
            el = None
        if el:
            analysis = await _analyze_element(el)
            if choose_fill_strategy(analysis) != FILL_SKIP:
                return el

    if fast_mode or not label:
        return None

    if label:
        root_handle = await page.evaluate_handle(_FIELD_ROOT_JS, label)
        root = root_handle.as_element() if root_handle else None
        if root:
            control = await root.evaluate_handle(_CONTROL_IN_ROOT_JS)
            el = control.as_element() if control else None
            if el:
                return el

    return None


_NOT_APPLICABLE_VALUES = frozenset({"na", "n/a", "none", "not applicable", "-", "—", "null"})

# Saved profile/answer values → common Greenhouse EEO option labels
_DEMOGRAPHIC_VALUE_ALIASES: dict[str, list[str]] = {
    "man": ["man", "male"],
    "male": ["man", "male"],
    "woman": ["woman", "female"],
    "female": ["woman", "female"],
    "heterosexual": ["heterosexual", "straight"],
    "south asian": ["south asian", "asian", "indian"],
    "no, i don't have a disability": [
        "no, i don't have a disability",
        "no, i do not have a disability",
        "no disability",
        "no",
    ],
    "i am not a protected veteran": [
        "i am not a protected veteran",
        "i am not a veteran",
        "not a veteran",
        "no",
    ],
}

_GENDER_VALUES = frozenset({"man", "male", "woman", "female"})


def _gender_values_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    if {left, right} <= {"man", "male"}:
        return True
    if {left, right} <= {"woman", "female"}:
        return True
    return False


_GENDER_LABEL_RE = re.compile(r"\bgender\b", re.I)
_GENDER_LABEL_EXCLUDE_RE = re.compile(r"identity|transgender|sexual", re.I)


def resolve_gender_select_value(value: str) -> str:
    """Map profile gender to common ATS dropdown labels (Male/Man, Female/Woman)."""
    text = str(value or "").strip()
    if re.fullmatch(r"man", text, re.I):
        return "Male"
    if re.fullmatch(r"woman", text, re.I):
        return "Female"
    return text


def resolve_select_fill_value(value: str, label: str = "") -> str:
    """Normalize saved answers to the option labels common on the target field."""
    value_str = str(value or "").strip()
    if not value_str or not label:
        return value_str
    if _GENDER_LABEL_RE.search(label) and not _GENDER_LABEL_EXCLUDE_RE.search(label):
        return resolve_gender_select_value(value_str)
    return value_str


def _alias_option_match_score(alias_norm: str, option_norm: str) -> float:
    """Score alias against option text without false positives like man→woman/management."""
    if alias_norm == option_norm:
        return 100.0
    gender_pairs = ({"man", "male"}, {"woman", "female"})
    if {alias_norm, option_norm} in gender_pairs:
        return 100.0
    if len(alias_norm) <= 3:
        return 0.0
    if alias_norm in option_norm or option_norm in alias_norm:
        return 85.0
    return 0.0


def demographic_option_aliases(value: str) -> list[str]:
    """Return value variants to match against dropdown option text."""
    norm = str(value or "").strip().lower()
    if not norm:
        return []
    aliases = _DEMOGRAPHIC_VALUE_ALIASES.get(norm, [norm])
    if norm not in aliases:
        aliases = [norm, *aliases]
    return aliases


def type_filter_tokens(value: str) -> list[str]:
    """
    Short strings to type into React-Select combobox filters.

    Greenhouse dropdowns filter on brief text (e.g. "No") — typing the full saved
    answer ("No, I don't have a disability") usually matches nothing.
    """
    value_str = str(value or "").strip()
    if not value_str:
        return []

    norm = _norm_match_text(value_str)
    tokens: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        t = str(token or "").strip()
        if not t:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        tokens.append(t)

    if " " not in value_str:
        add(value_str)

    norm_lower = norm.lower()
    if norm_lower == "man":
        add("Male")
    elif norm_lower == "woman":
        add("Female")

    for alias in sorted(demographic_option_aliases(norm), key=len):
        if len(alias) <= 20:
            add(alias.title() if alias in ("no", "yes") else alias)

    if (
        norm.startswith("no")
        or " dont " in f" {norm} "
        or " do not " in f" {norm} "
        or norm.startswith("i am not")
        or " not a " in norm
        or " not " in norm
    ):
        add("No")
    elif norm.startswith("yes"):
        add("Yes")

    parts = value_str.split()
    if parts and len(parts[0]) >= 3 and parts[0].lower() not in ("i", "a", "an", "the"):
        add(parts[0])

    add(value_str)
    return tokens


def best_replay_filter_token(value: str) -> str:
    """Single best filter token for fast replay — avoids looping many guesses."""
    tokens = type_filter_tokens(value)
    return tokens[0] if tokens else str(value or "").strip()


def replay_option_candidates(value: str) -> list[str]:
    """Ordered option labels to try clicking directly during replay."""
    value_str = str(value or "").strip()
    if not value_str:
        return []
    norm = value_str.lower()
    seen: set[str] = set()
    candidates: list[str] = []

    def add(candidate: str) -> None:
        text = str(candidate or "").strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(text)

    add(value_str)
    for alias in demographic_option_aliases(norm):
        add(alias)
        if alias in ("no", "yes"):
            add(alias.title())
    token = best_replay_filter_token(value_str)
    if token:
        add(token)
    return candidates


def is_not_applicable_value(value: str) -> bool:
    return str(value or "").strip().lower() in _NOT_APPLICABLE_VALUES


def extract_option_gpa(option_text: str) -> float | None:
    """Extract the GPA-like number from a dropdown label such as '3.8 out of 4.0'."""
    for token in re.findall(r"\d+\.?\d*", str(option_text or "")):
        try:
            num = float(token)
            if 0.0 <= num <= 5.0:
                return num
        except ValueError:
            continue
    return None


def is_numeric_select_value(value: str) -> bool:
    return bool(re.fullmatch(r"\d+\.?\d*", str(value or "").strip()))


def _norm_match_text(value: str) -> str:
    text = str(value or "").lower().replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score_option_match(value: str, option_text: str) -> float:
    """Score how well an option label matches the desired value (higher is better)."""
    value_raw = str(value or "").strip().lower()
    option_raw = str(option_text or "").strip().lower()
    if is_numeric_select_value(value_raw):
        value_norm = value_raw
        option_norm = option_raw
    else:
        value_norm = _norm_match_text(value)
        option_norm = _norm_match_text(option_text)
    if not value_norm or not option_norm:
        return 0.0
    if value_norm == option_norm:
        return 100.0

    if value_norm in _GENDER_VALUES or option_norm in _GENDER_VALUES:
        if not _gender_values_compatible(value_norm, option_norm):
            return 0.0

    if is_not_applicable_value(value_norm):
        if "not applicable" in option_norm or option_norm.startswith("other"):
            return 100.0
        return 0.0

    for alias in demographic_option_aliases(value_norm):
        alias_norm = _norm_match_text(alias)
        alias_score = _alias_option_match_score(alias_norm, option_norm)
        if alias_score > 0:
            return alias_score

    if is_numeric_select_value(value_norm):
        try:
            target = float(value_norm)
            option_gpa = extract_option_gpa(option_norm)
            if option_gpa is not None:
                diff = abs(option_gpa - target)
                if diff <= 0.15:
                    return max(50.0, 100.0 - diff * 100.0)
            return 0.0
        except ValueError:
            pass

    if value_norm in option_norm:
        return 80.0 + min(len(value_norm) / max(len(option_norm), 1), 1.0) * 15.0
    if option_norm in value_norm:
        return 75.0

    value_words = set(re.findall(r"\w+", value_norm))
    option_words = set(re.findall(r"\w+", option_norm))
    if value_words and option_words and not is_numeric_select_value(value_norm):
        overlap = len(value_words & option_words) / len(value_words)
        if overlap >= 0.5:
            return 50.0 + overlap * 35.0
    return 0.0


async def _click_option_safe(option: Any) -> bool:
    try:
        await option.scroll_into_view_if_needed()
        await option.click(timeout=2500)
        return True
    except Exception:
        try:
            await option.click(force=True, timeout=2500)
            return True
        except Exception:
            try:
                await option.evaluate("el => el.click()")
                return True
            except Exception:
                return False


async def _find_combobox_input(root: Any, el: Any) -> Any | None:
    for selector in (
        "input.select__input",
        "input[role='combobox']",
        ".select__control input[type='text']",
        ".select-shell input",
    ):
        found = await root.query_selector(selector)
        if found:
            return found
    if await el.evaluate("el => el.tagName.toLowerCase() === 'input'"):
        return el
    return None


async def _open_custom_select(page: Any, root: Any, el: Any, *, fast_mode: bool = False) -> Any | None:
    combobox_input = await _find_combobox_input(root, el)
    control = await root.query_selector(
        '[role="combobox"], .select__control, .select-shell input, button[aria-haspopup="listbox"]'
    )
    click_target = combobox_input or control or el
    await click_target.scroll_into_view_if_needed()
    await click_target.click(timeout=2000 if fast_mode else 3000)
    await page.wait_for_timeout(80 if fast_mode else 250)
    return combobox_input or click_target


async def _type_filter_value(page: Any, input_el: Any | None, value: str, *, fast_mode: bool = False) -> None:
    if not input_el:
        return
    is_input = await input_el.evaluate("el => el.tagName.toLowerCase() === 'input'")
    if not is_input:
        return
    await input_el.fill("")
    delay = 5 if fast_mode else 20
    await input_el.type(str(value), delay=delay)
    await page.wait_for_timeout(120 if fast_mode else 500)


async def _pick_option(page: Any, value: str, *, fast_mode: bool = False) -> bool:
    value_str = str(value).strip()
    if not value_str:
        return False

    settle_ms = 30 if fast_mode else 150

    exact = page.get_by_role("option", name=value_str, exact=True)
    if await exact.count() > 0 and await _click_option_safe(exact.first):
        await page.wait_for_timeout(settle_ms)
        return True

    option_locator = page.locator(
        ".select__menu [role='option'], .select__menu .select__option, "
        "[role='listbox'] [role='option'], .iti__country-list .iti__country, "
        ".demographic_question [role='option'], .demographic_question .select__option"
    )
    count = await option_locator.count()
    best_idx = -1
    best_score = 0.0
    numeric_mode = is_numeric_select_value(value_str) or is_not_applicable_value(value_str)
    visible_checked = 0
    for i in range(count):
        if fast_mode and visible_checked >= _FAST_OPTION_SCAN_LIMIT:
            break
        opt = option_locator.nth(i)
        try:
            if not numeric_mode and not await opt.is_visible():
                continue
            visible_checked += 1
            text = (await opt.inner_text()).strip()
            score = score_option_match(value_str, text)
            if score > best_score:
                best_score = score
                best_idx = i
        except Exception:
            continue

    if best_idx >= 0 and best_score >= 45.0:
        best_opt = option_locator.nth(best_idx)
        if numeric_mode:
            await best_opt.scroll_into_view_if_needed()
        if await _click_option_safe(best_opt):
            await page.wait_for_timeout(settle_ms)
            return True

    if not fast_mode:
        focused = page.locator(".select__option--is-focused, [role='option'][aria-selected='true']").first
        if await focused.count() > 0:
            text = (await focused.inner_text()).strip()
            if score_option_match(value_str, text) >= 45.0 and await _click_option_safe(focused):
                await page.wait_for_timeout(settle_ms)
                return True
            try:
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(settle_ms)
                return True
            except Exception:
                pass

    for candidate in replay_option_candidates(value_str):
        opt = page.get_by_role("option", name=candidate, exact=True)
        if await opt.count() > 0 and await _click_option_safe(opt.first):
            await page.wait_for_timeout(settle_ms)
            return True
        if not fast_mode:
            opt_partial = page.get_by_role("option", name=candidate)
            if await opt_partial.count() > 0 and await _click_option_safe(opt_partial.first):
                await page.wait_for_timeout(settle_ms)
                return True

    return False


async def _pick_option_in_root(root: Any, page: Any, value: str, *, fast_mode: bool = False) -> bool:
    """Pick an option scoped to a field root — avoids matching the wrong open menu."""
    value_str = str(value).strip()
    if not value_str:
        return False

    settle_ms = 30 if fast_mode else 150
    option_els = await root.query_selector_all(
        "[role='option'], .select__option, .select__menu [role='option']"
    )
    best_el = None
    best_score = 0.0
    visible_checked = 0
    for el in option_els:
        if fast_mode and visible_checked >= _FAST_OPTION_SCAN_LIMIT:
            break
        try:
            if not await el.is_visible():
                continue
            visible_checked += 1
            text = (await el.inner_text()).strip()
            score = score_option_match(value_str, text)
            if score > best_score:
                best_score = score
                best_el = el
        except Exception:
            continue

    if best_el is not None and best_score >= 45.0 and await _click_option_safe(best_el):
        await page.wait_for_timeout(settle_ms)
        return True

    for candidate in replay_option_candidates(value_str):
        for el in option_els:
            try:
                if not await el.is_visible():
                    continue
                text = (await el.inner_text()).strip()
                if text.lower() == candidate.lower() and await _click_option_safe(el):
                    await page.wait_for_timeout(settle_ms)
                    return True
            except Exception:
                continue

    return await _pick_option(page, value_str, fast_mode=fast_mode)


async def _read_phone_dial_code(page: Any) -> str:
    """Read the visible dial code from the intl-tel-input / Greenhouse country button."""
    try:
        return str(
            await page.evaluate(
                """() => {
                    const phone = document.querySelector('#phone');
                    const iti = phone?.closest('.iti') || document.querySelector('.iti');
                    const dialEl = iti?.querySelector('.iti__selected-dial-code');
                    if (dialEl) {
                        const dial = (dialEl.textContent || dialEl.innerText || '').trim();
                        if (dial) return dial;
                    }
                    const countryBtn =
                        iti?.querySelector('.iti__selected-country, .iti__selected-flag')
                        || document.querySelector('#country.iti__selected-country');
                    const meta = [
                        countryBtn?.getAttribute('aria-label') || '',
                        countryBtn?.getAttribute('title') || '',
                        countryBtn?.textContent || '',
                        countryBtn?.innerText || '',
                    ].join(' ');
                    const paren = meta.match(/\\(\\+(\\d+)\\)/);
                    if (paren) return '+' + paren[1];
                    const plus = meta.match(/\\+(\\d+)/);
                    if (plus) return '+' + plus[1];
                    if (/United States/i.test(meta)) return '+1';
                    return meta.trim();
                }"""
            )
            or ""
        ).strip()
    except Exception:
        return ""


async def _page_phone_dial_code(page: Any) -> str:
    return await _read_phone_dial_code(page)


async def _phone_country_already_set(page: Any, country_name: str, container: Any | None = None) -> bool:
    if container and await _iti_country_matches(container, country_name):
        return True
    dial = await _read_phone_dial_code(page)
    target = country_name.strip().lower()
    dial_lower = dial.lower()
    if target in ("united states", "us", "usa", "u.s.", "u.s.a."):
        if dial in ("+1", "1") or "+1" in dial or "united states" in dial_lower:
            return True
        if dial == "+93" or dial.endswith("93") or "afghanistan" in dial_lower:
            return False
    if dial == "+93" or dial.endswith("93"):
        return False
    return False


def _phone_country_search_tokens(country_name: str) -> list[str]:
    """Short type-ahead strings for the ITI country list filter."""
    target = country_name.strip().lower()
    if target in ("united states", "us", "usa", "u.s.", "u.s.a."):
        return ["united", "United States", "us"]
    return [country_name]


async def _open_phone_country_dropdown(page: Any, container_el: Any) -> None:
    for sel in (
        ".iti__selected-country",
        ".iti__selected-flag",
        '[id="country"].iti__selected-country',
    ):
        btn = page.locator(sel).first
        if await btn.count() > 0:
            try:
                await btn.scroll_into_view_if_needed()
                await btn.click(timeout=3000)
                await page.wait_for_timeout(350)
                return
            except Exception:
                try:
                    await btn.click(force=True, timeout=3000)
                    await page.wait_for_timeout(350)
                    return
                except Exception:
                    continue
    await _click_iti_opener(container_el)


async def _type_iti_country_filter(page: Any, container_el: Any, token: str) -> None:
    country_filter = page.locator('#country.select__input, [id="country"].select__input, .iti__search-input').first
    if await country_filter.count() > 0:
        try:
            await country_filter.click(timeout=2000)
            await country_filter.fill("", timeout=2000)
            await country_filter.type(token, delay=25)
            await page.wait_for_timeout(450)
            return
        except Exception:
            try:
                await country_filter.click(timeout=2000)
                await page.keyboard.type(token, delay=25)
                await page.wait_for_timeout(450)
                return
            except Exception:
                pass
    for scope in (container_el, page):
        if scope is page:
            search = page.locator(".iti__search-input:visible, .iti input[type='search']:visible").first
        else:
            search_handle = await container_el.query_selector(".iti__search-input, input[type='search']")
            search = search_handle
        if not search:
            continue
        try:
            if scope is page:
                await search.click(timeout=2000)
                await search.fill("", timeout=2000)
            else:
                await search.click(timeout=2000)
                await search.fill("", timeout=2000)
            await page.keyboard.type(token, delay=25)
            await page.wait_for_timeout(450)
            return
        except Exception:
            continue


async def _find_iti_container(page: Any, *, near_selector: str = "") -> Any | None:
    """Locate the intl-tel-input widget tied to the phone field."""
    near_selector = normalize_css_selector(near_selector)
    if near_selector:
        try:
            anchor = await page.query_selector(near_selector)
        except Exception:
            anchor = None
        if anchor:
            handle = await anchor.evaluate_handle("el => el.closest('.iti')")
            container = handle.as_element() if handle else None
            if container:
                return container

    for phone_selector in ("#phone", "input[type='tel'][name='phone']", "input[name='phone']", "input[type='tel']"):
        try:
            phone = await page.query_selector(phone_selector)
        except Exception:
            phone = None
        if phone:
            handle = await phone.evaluate_handle("el => el.closest('.iti')")
            container = handle.as_element() if handle else None
            if container:
                return container
    return None


async def _iti_country_matches(container: Any, country_name: str) -> bool:
    data = await container.evaluate(
        """el => {
            const btn = el.querySelector('.iti__selected-country, .iti__selected-flag');
            const dial = el.querySelector('.iti__selected-dial-code');
            const meta = [
                btn?.getAttribute('aria-label') || '',
                btn?.getAttribute('title') || '',
                btn?.textContent || '',
                dial?.innerText || dial?.textContent || '',
            ].join(' ');
            return { meta, dial: (dial?.innerText || dial?.textContent || '').trim() };
        }"""
    )
    meta = str(data.get("meta") or "").lower()
    dial = str(data.get("dial") or "").strip()
    target = country_name.strip().lower()
    if target and (target in meta or ("united states" in meta and target in ("united states", "us", "usa", "u.s."))):
        return True
    if target in ("united states", "us", "usa", "u.s.") and (
        dial in ("+1", "1") or "+1" in meta or "united states" in meta
    ):
        return True
    return False


async def _click_iti_opener(container: Any) -> None:
    for selector in (
        ".iti__selected-country",
        ".iti__selected-flag",
        ".iti__flag-container",
        ".iti__country-container",
    ):
        opener = await container.query_selector(selector)
        if not opener:
            continue
        try:
            await opener.click(timeout=2500)
            return
        except Exception:
            try:
                await opener.click(force=True, timeout=2500)
                return
            except Exception:
                try:
                    await opener.evaluate("el => el.click()")
                    return
                except Exception:
                    continue
    raise RuntimeError("Phone country opener not clickable")


async def _set_iti_country_via_js(page: Any, country_name: str) -> bool:
    """Use intl-tel-input API when available — most reliable on Greenhouse."""
    iso2 = ""
    target = country_name.strip().lower()
    if target in ("united states", "us", "usa", "u.s.", "u.s.a."):
        iso2 = "us"
    try:
        return bool(
            await page.evaluate(
                """({ countryName, iso2 }) => {
                    const input =
                        document.querySelector('#phone')
                        || document.querySelector('input[type="tel"][name="phone"]')
                        || document.querySelector('input[type="tel"]');
                    if (!input) return false;
                    const globals = window.intlTelInputGlobals;
                    if (globals && typeof globals.getInstance === 'function') {
                        const iti = globals.getInstance(input);
                        if (iti && typeof iti.setCountry === 'function') {
                            if (iso2) {
                                iti.setCountry(iso2);
                                if ((iti.getSelectedCountryData()?.iso2 || '').toLowerCase() === iso2) {
                                    return true;
                                }
                            } else {
                                const lower = String(countryName || '').toLowerCase();
                                const countries = iti.getCountryData?.() || [];
                                const match = countries.find(
                                    (c) => c.name.toLowerCase() === lower || c.name.toLowerCase().includes(lower)
                                );
                                if (match) {
                                    iti.setCountry(match.iso2);
                                    return true;
                                }
                            }
                        }
                    }
                    const itiRoot = input.closest('.iti');
                    const selected = itiRoot?.querySelector('.iti__selected-country, .iti__selected-flag');
                    if (selected) selected.click();
                    const targetIso = iso2 || '';
                    const countryNode = targetIso
                        ? document.querySelector(
                              `.iti__country-list .iti__country[data-country-code="${targetIso}"], .iti__country[data-country-code="${targetIso}"]`
                          )
                        : null;
                    if (countryNode) {
                        countryNode.click();
                        const dial = itiRoot?.querySelector('.iti__selected-dial-code')?.textContent || '';
                        return targetIso === 'us' ? dial.includes('1') : true;
                    }
                    return false;
                }""",
                {"countryName": country_name, "iso2": iso2},
            )
        )
    except Exception:
        return False


async def _click_iti_country_option(page: Any, country_name: str) -> bool:
    """Click a country row in the open ITI list — never press Enter (Afghanistan stays focused by default)."""
    target = country_name.strip().lower()
    candidates: list[Any] = []

    if target in ("united states", "us", "usa", "u.s.", "u.s.a."):
        for label in ("United States +1", "United States", "United States+1"):
            loc = page.get_by_text(label, exact=False)
            if await loc.count() > 0:
                candidates.append(loc.first)
        for sel in (
            '.iti__country-list .iti__country[data-country-code="us"]',
            '.iti__country[data-country-code="us"]',
            '[role="option"]:has-text("United States")',
            '.select__option:has-text("United States")',
        ):
            loc = page.locator(sel).first
            if await loc.count() > 0:
                candidates.append(loc)

    loc = page.locator(".iti__country-list .iti__country, .iti__country").filter(has_text=country_name)
    count = await loc.count()
    for i in range(count):
        candidates.append(loc.nth(i))

    seen: set[str] = set()
    for opt in candidates:
        try:
            oid = str(await opt.evaluate("el => el.outerHTML.slice(0, 120)"))
            if oid in seen:
                continue
            seen.add(oid)
            if not await opt.is_visible():
                continue
            text = (await opt.inner_text()).strip()
            if target in ("united states", "us", "usa", "u.s.", "u.s.a."):
                if "+1" not in text.replace(" ", "") and "United States" not in text:
                    continue
            if await _click_option_safe(opt):
                await page.wait_for_timeout(250)
                if await _phone_country_already_set(page, country_name):
                    return True
                dial = await _read_phone_dial_code(page)
                if target in ("united states", "us", "usa", "u.s.", "u.s.a."):
                    return "+1" in dial or "united states" in dial.lower()
                return True
        except Exception:
            continue
    return False


async def _fill_phone_country(page: Any, country_name: str, *, near_selector: str = "", fast_mode: bool = False) -> None:
    container_el = await _find_iti_container(page, near_selector=near_selector)
    if await _phone_country_already_set(page, country_name, container_el):
        return

    if await _set_iti_country_via_js(page, country_name):
        if await _phone_country_already_set(page, country_name, container_el):
            return

    if fast_mode:
        dial = await _read_phone_dial_code(page)
        if await _phone_country_already_set(page, country_name, container_el):
            return
        raise RuntimeError(f"Could not select phone country quickly: {country_name} (dial={dial or 'unknown'})")

    if not container_el:
        raise RuntimeError("Phone country widget not found")

    await container_el.scroll_into_view_if_needed()

    for attempt in range(2):
        await _open_phone_country_dropdown(page, container_el)

        if await _click_iti_country_option(page, country_name):
            if await _phone_country_already_set(page, country_name, container_el):
                return

        for token in _phone_country_search_tokens(country_name):
            await _open_phone_country_dropdown(page, container_el)
            await _type_iti_country_filter(page, container_el, token)
            if await _click_iti_country_option(page, country_name):
                if await _phone_country_already_set(page, country_name, container_el):
                    return

        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
        except Exception:
            pass

    if await _set_iti_country_via_js(page, country_name):
        if await _phone_country_already_set(page, country_name, container_el):
            return

    dial = await _read_phone_dial_code(page)
    raise RuntimeError(f"Could not select phone country: {country_name} (dial still {dial or 'unknown'})")


async def _dismiss_open_select_menus(page: Any, *, fast_mode: bool = False) -> None:
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(30 if fast_mode else 100)
    except Exception:
        pass


async def _attempt_custom_select_pick(
    page: Any, root: Any, el: Any, value_str: str, *, fast_mode: bool = False
) -> bool:
    """Type short filter tokens, then pick the option that best matches the full saved value."""
    escape_wait = 50 if fast_mode else 150

    await _dismiss_open_select_menus(page, fast_mode=fast_mode)
    await _open_custom_select(page, root, el, fast_mode=fast_mode)
    if await _pick_option_in_root(root, page, value_str, fast_mode=fast_mode):
        return True
    if await _pick_option(page, value_str, fast_mode=fast_mode):
        return True

    if fast_mode:
        token = best_replay_filter_token(value_str)
        if not token:
            return False

        await _dismiss_open_select_menus(page, fast_mode=True)
        combobox_input = await _open_custom_select(page, root, el, fast_mode=True)
        await _type_filter_value(page, combobox_input, token, fast_mode=True)
        if await _pick_option_in_root(root, page, value_str, fast_mode=True):
            return True
        return await _pick_option(page, value_str, fast_mode=True)

    if is_numeric_select_value(value_str) or is_not_applicable_value(value_str):
        combobox_input = await _open_custom_select(page, root, el, fast_mode=fast_mode)
        await _type_filter_value(page, combobox_input, value_str, fast_mode=fast_mode)
        return await _pick_option(page, value_str, fast_mode=fast_mode)

    for token in type_filter_tokens(value_str):
        combobox_input = await _open_custom_select(page, root, el, fast_mode=fast_mode)
        await _type_filter_value(page, combobox_input, token, fast_mode=fast_mode)
        if await _pick_option(page, value_str, fast_mode=fast_mode):
            return True
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(escape_wait)
        except Exception:
            pass
    return False


async def _fill_native_select(el: Any, value: str, *, label: str = "") -> None:
    """Select a native <select> option, matching aliases like Man→Male."""
    value_str = resolve_select_fill_value(str(value or "").strip(), label)
    if not value_str:
        return

    for candidate in replay_option_candidates(value_str):
        try:
            await el.select_option(label=candidate)
            return
        except Exception:
            pass
        try:
            await el.select_option(value=candidate)
            return
        except Exception:
            pass

    options = await el.evaluate(
        """el => [...el.options].map(o => ({
            value: (o.value || '').trim(),
            label: (o.textContent || o.label || '').trim(),
        })).filter(o => o.value || o.label)"""
    )
    best_value = ""
    best_score = 0.0
    for opt in options or []:
        opt_label = str(opt.get("label") or "")
        opt_value = str(opt.get("value") or "")
        for candidate in (opt_label, opt_value):
            if not candidate:
                continue
            score = score_option_match(value_str, candidate)
            if score > best_score:
                best_score = score
                best_value = opt_value or opt_label

    if best_score >= 45.0 and best_value:
        try:
            await el.select_option(value=best_value)
            return
        except Exception:
            pass
        try:
            await el.select_option(label=best_value)
            return
        except Exception:
            pass

    raise RuntimeError(f"Could not select dropdown option: {value_str}")


async def _fill_custom_select(page: Any, el: Any, value: str, *, label: str = "", fast_mode: bool = False) -> None:
    value_str = resolve_select_fill_value(str(value).strip(), label)
    if not value_str:
        return

    field_root = await el.evaluate_handle(
        "el => el.closest('.field, .application-question, .question, li.application-question, .demographic_question, .field-wrapper') || el"
    )
    root = field_root.as_element() if field_root else el
    try:
        await root.scroll_into_view_if_needed()
    except Exception:
        pass

    if await _attempt_custom_select_pick(page, root, el, value_str, fast_mode=fast_mode):
        return

    try:
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(80 if fast_mode else 200)
    except Exception:
        pass

    if label and not fast_mode:
        labeled = page.locator(
            ".field, .application-question, .question, .demographic_question, .field-wrapper"
        ).filter(has_text=label[:60]).first
        if await labeled.count() > 0:
            inner_root = await labeled.element_handle()
            if inner_root and await _attempt_custom_select_pick(page, inner_root, el, value_str, fast_mode=fast_mode):
                return

    raise RuntimeError(f"Could not select dropdown option: {value_str}")


async def _try_direct_replay_fill(
    page: Any,
    field: dict[str, Any],
    value: Any,
    *,
    profile: dict[str, Any] | None = None,
) -> tuple[bool, str] | None:
    """Fast path for replay: use saved selector/type without scanning the whole form."""
    _ = profile
    selector = normalize_css_selector(str(field.get("selector") or field.get("selectorHint") or ""))
    if not selector:
        return None

    action_type = str(field.get("type") or "")
    field_type = effective_replay_field_type(field)
    value_str = str(value or "").strip()

    if action_type == "upload_document" or field_type == "file":
        if not value_str:
            return None
        el = await page.query_selector(selector)
        if not el:
            return None
        await _set_input_file(
            el,
            value_str,
            file_name=str(field.get("fileName") or field.get("documentFileName") or ""),
        )
        return True, "file_direct"

    el = await page.query_selector(selector)
    if el:
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        input_type = await el.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
        if tag == "input" and input_type == "file":
            if value_str:
                await _set_input_file(
                    el,
                    value_str,
                    file_name=str(field.get("fileName") or field.get("documentFileName") or ""),
                )
                return True, "file_direct"
            return None
        if tag in ("input", "textarea") and field_type in _SELECT_FIELD_TYPES:
            if input_type == "email":
                field_type = "email"
            elif input_type == "tel":
                field_type = "tel"
            else:
                field_type = "text"

    if field_type in _SELECT_FIELD_TYPES:
        if not value_str:
            return None
        if not el:
            el = await page.query_selector(selector)
        if not el:
            return None
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        role = await el.evaluate("el => (el.getAttribute('role') || '').toLowerCase()")
        label = str(field.get("fieldLabel") or field.get("label") or "")
        if tag == "select":
            await _fill_native_select(el, value_str, label=label)
            return True, "native_select_direct"
        if tag in ("input", "textarea") and role == "combobox":
            await _fill_custom_select(page, el, value_str, label=label, fast_mode=True)
            return True, "custom_select_direct"
        await _fill_native_select(el, value_str, label=label)
        return True, "native_select_direct"

    if field_type in _TEXT_FIELD_TYPES or action_type in ("fill_field", "fill_text"):
        if not value_str:
            return None
        if not el:
            el = await page.query_selector(selector)
        if not el:
            return None
        await el.fill(value_str, timeout=3000)
        return True, "text_direct"

    return None


async def fill_field(
    page: Any,
    field: dict[str, Any],
    value: Any,
    *,
    profile: dict[str, Any] | None = None,
    fast_mode: bool = False,
    replay_only: bool = False,
) -> tuple[bool, str]:
    """
    Fill one field using live DOM analysis.
    Returns (success, reason). Never blocks on invisible internal widget parts.
    """
    meta = _field_meta(field)
    label = meta["label"]
    selector = meta["selector"]

    phone_country_candidate = (
        field.get("normalizedKey") == "phone_country"
        or is_phone_country_field(
            label,
            selector_hint=selector or str(field.get("selectorHint") or ""),
            field_id=meta["fieldId"],
            name=meta["name"],
        )
        or selector.lower() in ("#country", '[id="country"]', "[name='country']")
    )
    if phone_country_candidate:
        peek = await page.query_selector(selector) if selector else None
        if peek:
            peek_analysis = await _analyze_element(peek)
            if not (
                peek_analysis.get("itiCountry")
                or peek_analysis.get("inIti")
                or field.get("normalizedKey") == "phone_country"
            ):
                phone_country_candidate = False

    if phone_country_candidate:
        country = str(value or infer_phone_country(profile or {}))
        if await _phone_country_already_set(page, country):
            return True, "phone_country_already_set"
        try:
            await _fill_phone_country(page, country, near_selector=selector, fast_mode=fast_mode)
        except Exception:
            if await _phone_country_already_set(page, country):
                return True, "phone_country_already_set"
            raise
        if not await _phone_country_already_set(page, country):
            dial = await _read_phone_dial_code(page)
            raise RuntimeError(f"Phone country not set to {country} (dial={dial or 'unknown'})")
        return True, "phone_country"

    if fast_mode or replay_only:
        direct = await _try_direct_replay_fill(page, field, value, profile=profile)
        if direct is not None:
            return direct
        if replay_only:
            return False, "saved_selector_miss"

    el = await _resolve_element(page, field, fast_mode=fast_mode)
    if not el:
        return False, "element_not_found"

    analysis = await _analyze_element(el)
    strategy = choose_fill_strategy(analysis, profile=profile)
    if strategy == FILL_SKIP:
        return False, "skip_not_fillable"

    value_str = str(value).strip()
    if not value_str and strategy != FILL_CHECKBOX:
        return False, "empty_value"

    if strategy == FILL_PHONE_COUNTRY:
        await _fill_phone_country(
            page,
            value_str or infer_phone_country(profile or {}),
            near_selector=selector,
            fast_mode=fast_mode,
        )
        return True, "phone_country"

    if strategy == FILL_NATIVE_SELECT:
        try:
            await _fill_native_select(el, value_str, label=label)
            return True, "native_select"
        except Exception:
            try:
                await _fill_custom_select(page, el, value_str, label=label, fast_mode=fast_mode)
                return True, "custom_select_fallback"
            except Exception as exc:
                return False, str(exc)

    if strategy == FILL_CUSTOM_SELECT:
        if not fast_mode and any(
            token in label.lower()
            for token in ("gender", "veteran", "disability", "ethnic", "orientation", "transgender")
        ):
            try:
                await page.evaluate("window.scrollTo(0, Math.max(document.body.scrollHeight * 0.65, 0))")
                await page.wait_for_timeout(400)
            except Exception:
                pass
        await _fill_custom_select(page, el, value_str, label=label, fast_mode=fast_mode)
        return True, "custom_select"

    if strategy == FILL_CHECKBOX:
        checked = await el.evaluate("el => el.checked")
        if not checked:
            await el.click(timeout=3000)
        return True, "checkbox"

    if strategy == FILL_FILE:
        await _set_input_file(
            el,
            value_str,
            file_name=str(field.get("fileName") or field.get("documentFileName") or ""),
        )
        return True, "file"

    if strategy == FILL_TEXT:
        if not await el.is_visible():
            return False, "not_visible"
        await el.fill(value_str, timeout=3000 if fast_mode else 5000)
        return True, "text"

    return False, "unsupported"


_TEXT_FIELD_TYPES = frozenset({"text", "email", "tel", "url", "number", "search", "textarea"})
_SELECT_FIELD_TYPES = frozenset({"select-one", "select"})

_REPLAY_TEXT_NORMALIZED_KEYS = frozenset({
    "first_name",
    "last_name",
    "preferred_first_name",
    "full_name",
    "linkedin_profile",
    "linkedin",
    "website",
    "portfolio",
    "github",
    "location",
    "current_title",
    "current_company",
})

_REPLAY_TEXT_SELECTORS = frozenset({
    "#first_name",
    "#last_name",
    "#preferred_name",
    "#email",
    "#phone",
    "#linkedin",
    "#website",
    "input[name='job_application[first_name]']",
    "input[name='job_application[last_name]']",
    "input[name='job_application[email]']",
    "input[name='job_application[phone]']",
})


def effective_replay_field_type(action: dict[str, Any]) -> str:
    """Correct misclassified Greenhouse field types saved during prep (e.g. text inputs as select-one)."""
    action_type = str(action.get("type") or "")
    if action_type == "upload_document":
        return "file"

    selector = normalize_css_selector(str(action.get("selector") or action.get("selectorHint") or ""))
    sel_lower = selector.lower()
    normalized_key = str(action.get("normalizedKey") or "").lower()
    field_type = str(action.get("fieldType") or "text").lower()

    if normalized_key == "resume" or sel_lower in {"#resume", "input[type='file']"}:
        return "file"
    if normalized_key == "email" or sel_lower == "#email":
        return "email"
    if normalized_key == "phone" or sel_lower == "#phone":
        return "tel"
    if normalized_key in _REPLAY_TEXT_NORMALIZED_KEYS or sel_lower in _REPLAY_TEXT_SELECTORS:
        return "text"
    return field_type


def _replay_action_key(action: dict[str, Any]) -> str:
    """Stable key for deduping replay results within one pass."""
    field_id = str(action.get("fieldId") or "").strip()
    if field_id:
        return field_id
    selector = normalize_css_selector(str(action.get("selector") or action.get("selectorHint") or ""))
    if selector:
        return selector
    return str(action.get("fieldLabel") or action.get("normalizedKey") or id(action))


def _mark_filled(action: dict[str, Any], results: dict[str, Any], filled_keys: set[str]) -> None:
    key = _replay_action_key(action)
    if key in filled_keys:
        return
    filled_keys.add(key)
    results["filled"].append(action)


_BATCH_TEXT_FILL_JS = """(entries) => {
    const inputSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    const areaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
    const results = [];
    for (const { selector, value } of entries) {
        try {
            const el = document.querySelector(selector);
            if (!el) {
                results.push({ selector, ok: false, reason: 'not_found' });
                continue;
            }
            const tag = el.tagName.toLowerCase();
            const type = (el.type || '').toLowerCase();
            if (type === 'file' || type === 'hidden' || type === 'checkbox' || type === 'radio') {
                results.push({ selector, ok: false, reason: 'skip_type' });
                continue;
            }
            if (tag === 'select') {
                results.push({ selector, ok: false, reason: 'is_select' });
                continue;
            }
            if (el.getAttribute('role') === 'combobox' || el.readOnly) {
                results.push({ selector, ok: false, reason: 'is_combobox' });
                continue;
            }
            const setter = tag === 'textarea' ? areaSetter : inputSetter;
            if (setter) {
                setter.call(el, value);
            } else {
                el.value = value;
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            results.push({ selector, ok: true });
        } catch (err) {
            results.push({ selector, ok: false, reason: String(err) });
        }
    }
    return results;
}"""


async def _fill_saved_select_fast(
    page: Any,
    action: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Replay a saved dropdown value with at most two open/type/click attempts."""
    _ = profile
    selector = normalize_css_selector(str(action.get("selector") or action.get("selectorHint") or ""))
    value = str(action.get("value") or "").strip()
    label = str(action.get("fieldLabel") or action.get("label") or "")
    if not selector or not value:
        return False, "missing_selector_or_value"

    el = await page.query_selector(selector)
    if not el and label:
        el = await _resolve_element(page, {"selector": "", "fieldLabel": label, "label": label}, fast_mode=True)
    if not el:
        return False, "element_not_found"

    tag = await el.evaluate("el => el.tagName.toLowerCase()")
    if tag == "select":
        try:
            await _fill_native_select(el, value, label=label)
            return True, "native_select"
        except Exception:
            pass

    analysis = await _analyze_element(el)
    if choose_fill_strategy(analysis) == FILL_SKIP:
        custom_selector = await resolve_custom_select_selector(page, el)
        if custom_selector:
            el = await page.query_selector(custom_selector)
        if not el and label:
            el = await _resolve_element(
                page,
                {"selector": selector, "fieldLabel": label, "label": label},
                fast_mode=True,
            )
    if not el:
        return False, "element_not_found"

    try:
        await _fill_custom_select(page, el, value, label=label, fast_mode=True)
        await _dismiss_open_select_menus(page, fast_mode=True)
        return True, "custom_select_fast"
    except Exception as exc:
        await _dismiss_open_select_menus(page, fast_mode=True)
        return False, str(exc)


async def _replay_field_with_timeout(
    coro: Any,
    action: dict[str, Any],
    *,
    timeout_sec: float = _REPLAY_FIELD_TIMEOUT_SEC,
) -> tuple[Any, str | None]:
    """Run one replay step with a hard timeout so one widget cannot block quick apply."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec), None
    except asyncio.TimeoutError:
        return None, "replay_field_timeout"
    except Exception as exc:
        return None, str(exc)


async def fill_page_fast_replay(
    page: Any,
    actions: list[dict[str, Any]],
    *,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Replay saved fill actions with minimal per-field DOM work.

    Text/tel/email fields are injected in one browser evaluate(); selects and
    special widgets fall back to fill_field(fast_mode=True).
    """
    results: dict[str, Any] = {"filled": [], "skipped": [], "errors": []}
    filled_keys: set[str] = set()
    upload_actions: list[dict[str, Any]] = []
    text_batch: list[dict[str, Any]] = []
    select_actions: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    for action in actions:
        action_type = str(action.get("type") or "")
        if action_type == "upload_document":
            upload_actions.append(action)
            continue

        field_type = effective_replay_field_type(action)
        if action.get("normalizedKey") == "phone_country":
            deferred.append(action)
            continue

        selector = normalize_css_selector(str(action.get("selector") or action.get("selectorHint") or ""))
        value = action.get("value")
        if field_type == "file":
            upload_actions.append(action)
            continue
        if field_type in _SELECT_FIELD_TYPES and selector and value is not None and str(value).strip():
            select_actions.append(action)
        elif field_type in _TEXT_FIELD_TYPES and selector and value is not None and str(value).strip():
            text_batch.append({"selector": selector, "value": str(value), "action": action})
        else:
            deferred.append(action)

    for action in upload_actions:
        file_path = str(action.get("filePath") or action.get("value") or "").strip()
        if not file_path:
            results["skipped"].append({"action": action, "reason": "missing_file_path"})
            continue
        outcome, err = await _replay_field_with_timeout(
            fill_field(page, action, file_path, profile=profile, fast_mode=True),
            action,
        )
        if err == "replay_field_timeout":
            results["errors"].append({"action": action, "error": err})
            results["skipped"].append({"action": action, "reason": err})
            continue
        if err:
            results["errors"].append({"action": action, "error": err})
            results["skipped"].append({"action": action, "reason": err})
            continue
        ok, reason = outcome
        if ok:
            _mark_filled(action, results, filled_keys)
        else:
            results["skipped"].append({"action": action, "reason": reason})

    if text_batch:
        try:
            batch_payload = [{"selector": item["selector"], "value": item["value"]} for item in text_batch]
            batch_results = await page.evaluate(_BATCH_TEXT_FILL_JS, batch_payload)
            for item, outcome in zip(text_batch, batch_results, strict=False):
                if outcome.get("ok"):
                    _mark_filled(item["action"], results, filled_keys)
                else:
                    deferred.append(item["action"])
        except Exception as exc:
            results["errors"].append({"action": "batch_text", "error": str(exc)})
            deferred.extend(item["action"] for item in text_batch)

    for action in select_actions:
        action_key = _replay_action_key(action)
        outcome, err = await _replay_field_with_timeout(
            _fill_saved_select_fast(page, action, profile=profile),
            action,
            timeout_sec=_REPLAY_SELECT_TIMEOUT_SEC,
        )
        if err == "replay_field_timeout":
            if action_key not in filled_keys:
                deferred.append(action)
            continue
        if err:
            results["errors"].append({"action": action, "error": err})
            if action_key not in filled_keys:
                deferred.append(action)
            continue
        ok, reason = outcome
        if ok:
            _mark_filled(action, results, filled_keys)
        elif action_key not in filled_keys:
            deferred.append(action)
            results["skipped"].append({"action": action, "reason": reason})

    for action in deferred:
        action_key = _replay_action_key(action)
        if action_key in filled_keys:
            continue
        action_type = str(action.get("type") or "")
        if action_type == "upload_document":
            value = action.get("filePath") or action.get("value") or ""
        else:
            value = action.get("value", "")
        outcome, err = await _replay_field_with_timeout(
            fill_field(page, action, value, profile=profile, fast_mode=True, replay_only=True),
            action,
        )
        if err == "replay_field_timeout":
            results["errors"].append({"action": action, "error": err})
            results["skipped"].append({"action": action, "reason": err})
            continue
        if err:
            results["errors"].append({"action": action, "error": err})
            continue
        ok, reason = outcome
        if ok:
            _mark_filled(action, results, filled_keys)
        else:
            results["skipped"].append({"action": action, "reason": reason or err or "deferred_miss"})

    return results
