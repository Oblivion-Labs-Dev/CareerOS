"""Pre-fill and post-fill validation for mapped fields."""

from __future__ import annotations

from typing import Any

from app.services.application_assistant.answer_classification import AnswerClassification
from app.services.application_assistant.canonical_registry import SENSITIVE_CANONICAL_KEYS
from app.services.application_assistant.answer_classification import is_phone_country_field
from app.services.application_assistant.css_selectors import normalize_css_selector
from app.services.application_assistant.submission_guard import validate_action_allowed


async def resolve_fill_action_type(page: Any, field: dict[str, Any]) -> str:
    """Choose fill strategy from the live DOM — never trust stale mapped fieldType."""
    field_type = str(field.get("fieldType", "text")).lower()
    if field_type == "file":
        return "upload_document"
    selector = normalize_css_selector(field.get("selectorHint") or "")
    if not selector:
        return "fill_field"
    try:
        info = await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                return {
                    tag: el.tagName.toLowerCase(),
                    type: (el.getAttribute('type') || '').toLowerCase(),
                    role: (el.getAttribute('role') || '').toLowerCase(),
                    ariaHaspopup: (el.getAttribute('aria-haspopup') || '').toLowerCase(),
                };
            }""",
            selector,
        )
    except Exception:
        info = None
    if not info:
        return "fill_field"
    if info.get("type") == "file":
        return "upload_document"
    return "fill_field"


async def field_still_empty(page: Any, selector: str, field_type: str) -> bool:
    selector = normalize_css_selector(selector)
    if not selector:
        return False
    try:
        return bool(
            await page.evaluate(
                """([sel, ftype]) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    if (ftype === 'file') return !(el.files && el.files.length);
                    if (el.type === 'checkbox' || el.type === 'radio') return !el.checked;
                    const val = ('value' in el) ? String(el.value || '').trim() : '';
                    return val === '';
                }""",
                [selector, field_type],
            )
        )
    except Exception:
        return False


async def locator_resolves_uniquely(page: Any, selector: str) -> bool:
    selector = normalize_css_selector(selector)
    if not selector:
        return False
    try:
        count = await page.evaluate("(sel) => document.querySelectorAll(sel).length", selector)
        return count == 1
    except Exception:
        return False


def validate_mapping_for_fill(
    field: dict[str, Any],
    *,
    auto_confidence: float,
    review_confidence: float,
    review_mode: bool = False,
) -> tuple[bool, str]:
    """Deterministic pre-fill policy checks."""
    classification = field.get("classification", "unknown")
    if classification in (AnswerClassification.MANUAL_ONLY.value, "sensitive", "prohibited"):
        return False, "manual_or_sensitive"
    if classification == AnswerClassification.UNKNOWN.value and field.get("requiresUserReview") and not review_mode:
        return False, "requires_review"
    if not field.get("proposedValue") and field.get("fieldType") != "file":
        return False, "no_value"
    if field.get("fieldType") == "file" and not field.get("proposedValue"):
        return False, "no_file"

    confidence = float(field.get("confidence") or 0)
    canonical = field.get("canonicalKey") or ""
    if canonical in SENSITIVE_CANONICAL_KEYS and classification != AnswerClassification.VERIFIED.value:
        return False, "sensitive_unverified"

    if review_mode and classification == AnswerClassification.VERIFIED.value:
        selector = normalize_css_selector(field.get("selectorHint") or "")
        if not selector:
            return False, "no_locator"
        action_type = "upload_document" if field.get("fieldType") == "file" else "fill_text"
        allowed, reason = validate_action_allowed(action_type)
        if not allowed:
            return False, reason
        return True, "ok"

    if confidence < review_confidence:
        return False, "low_confidence"

    if confidence < auto_confidence and field.get("requiresUserReview"):
        return False, "review_required"

    selector = normalize_css_selector(field.get("selectorHint") or "")
    if not selector:
        return False, "no_locator"

    action_type = "upload_document" if field.get("fieldType") == "file" else "fill_text"
    allowed, reason = validate_action_allowed(action_type)
    if not allowed:
        return False, reason

    return True, "ok"


async def validate_mapping_on_page(
    page: Any,
    field: dict[str, Any],
    *,
    review_mode: bool = False,
) -> tuple[bool, str]:
    if review_mode and field.get("classification") == AnswerClassification.VERIFIED.value:
        return True, "ok"
    selector = normalize_css_selector(field.get("selectorHint") or "")
    if not await locator_resolves_uniquely(page, selector):
        return False, "locator_not_unique"
    if not await field_still_empty(page, selector, str(field.get("fieldType", "text"))):
        return False, "field_already_has_value"
    return True, "ok"


async def verify_filled_value(page: Any, field: dict[str, Any], expected: Any) -> bool:
    if field.get("normalizedKey") == "phone_country" or is_phone_country_field(
        str(field.get("label") or ""),
        field_id=str(field.get("id") or field.get("fieldId") or ""),
        selector_hint=str(field.get("selectorHint") or ""),
        name=str(field.get("name") or ""),
    ):
        from app.services.application_assistant.field_fill_engine import _phone_country_already_set

        return await _phone_country_already_set(page, str(expected or "United States"))

    selector = normalize_css_selector(field.get("selectorHint") or "")
    field_type = str(field.get("fieldType", "text")).lower()
    if not selector or expected is None:
        return False
    try:
        actual = await page.evaluate(
            """([sel, ftype]) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                if (ftype === 'file') {
                    if (!el.files || !el.files.length) return '';
                    return el.files[0].name || 'file';
                }
                if (el.tagName === 'SELECT') return el.options[el.selectedIndex]?.text || el.value || '';
                return el.value || '';
            }""",
            [selector, field_type],
        )
    except Exception:
        return False

    if field_type == "file":
        return bool(actual) and str(expected).split("\\")[-1].split("/")[-1] in str(actual)
    return str(actual).strip() == str(expected).strip()
