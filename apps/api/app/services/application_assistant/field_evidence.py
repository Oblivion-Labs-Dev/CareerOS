"""Structured page evidence for the field-mapping agent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.application_assistant.css_selectors import normalize_css_selector
from app.services.application_assistant.field_options import merge_field_options, normalize_field_options
from app.services.application_assistant.providers.base import FormField

FIELD_SCREENSHOTS_DIR = Path(__file__).resolve().parents[3] / "data" / "application_assistant" / "field_screenshots"
FIELD_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _stable_field_id(index: int, field: FormField | dict[str, Any]) -> str:
    el_id = field.id if isinstance(field, FormField) else field.get("id") or field.get("name")
    if el_id:
        safe = re.sub(r"[^\w\-]", "_", str(el_id))[:48]
        return f"field_{safe}"
    norm = field.normalized_key if isinstance(field, FormField) else field.get("normalizedKey", "field")
    safe = re.sub(r"[^\w\-]", "_", str(norm))[:48]
    return f"field_{index}_{safe}"


def _locator_candidates(field: FormField | dict[str, Any]) -> list[dict[str, str]]:
    if isinstance(field, FormField):
        label, el_id, name, hint = field.label, field.id, field.name, field.selector_hint
    else:
        label, el_id, name, hint = (
            field.get("label", ""),
            field.get("id", ""),
            field.get("name", ""),
            field.get("selectorHint", ""),
        )
    candidates: list[dict[str, str]] = []
    if label:
        candidates.append({"strategy": "label", "value": label})
    if el_id:
        candidates.append({"strategy": "id", "value": str(el_id)})
    if name:
        candidates.append({"strategy": "name", "value": str(name)})
    if hint:
        candidates.append({"strategy": "css", "value": normalize_css_selector(str(hint))})
    return candidates



_EXTRACT_OPTIONS_JS = """(sel) => {
    const add = (set, value) => {
        const text = String(value || '').replace(/\\s+/g, ' ').trim();
        if (!text) return;
        const lower = text.toLowerCase();
        if (lower.startsWith('select') || lower.startsWith('choose') || lower === '--') return;
        set.add(text);
    };

    const el = document.querySelector(sel);
    if (!el) return [];

    const texts = new Set();

    if (el.tagName === 'SELECT') {
        for (const opt of el.options) add(texts, opt.textContent || opt.label || opt.value);
        return Array.from(texts);
    }

    const name = el.getAttribute('name');
    if (name) {
        const escaped = (window.CSS && CSS.escape) ? CSS.escape(name) : name.replace(/"/g, '\\\\"');
        for (const radio of document.querySelectorAll(`input[type="radio"][name="${escaped}"]`)) {
            const label = radio.labels && radio.labels[0] ? radio.labels[0].textContent : radio.value;
            add(texts, label || radio.value);
        }
        if (texts.size) return Array.from(texts);
    }

    const container = el.closest('.field, .application-field, .select-shell, .select__container, [class*="select"]') || el.parentElement;
    const scopes = [container].filter(Boolean);
    for (const scope of scopes) {
        scope.querySelectorAll('[role="option"], .select__option, .menu-item, li[data-value], option').forEach((node) => {
            if (node.closest('.iti, .iti__country-list')) return;
            add(texts, node.textContent || node.getAttribute('data-value') || node.getAttribute('value'));
        });
        if (texts.size) break;
    }

    const controlsId = el.getAttribute('aria-controls');
    if (controlsId) {
        const listbox = document.getElementById(controlsId);
        if (listbox) {
            listbox.querySelectorAll('[role="option"], li, .select__option').forEach((node) => {
                add(texts, node.textContent || node.getAttribute('data-value'));
            });
        }
    }

    return Array.from(texts).slice(0, 50);
}"""


async def extract_dom_field_options(page: Any, selector: str, *, try_open: bool = True) -> list[str]:
    """Read dropdown/radio options from the live application form."""
    if not selector:
        return []
    try:
        options = normalize_field_options(await page.evaluate(_EXTRACT_OPTIONS_JS, selector))
        if options or not try_open:
            return options

        locator = page.locator(selector).first
        if await locator.count() == 0:
            return options

        aria_haspopup = await locator.get_attribute("aria-haspopup")
        role = await locator.get_attribute("role") or ""
        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
        if role == "combobox" or tag == "select" or aria_haspopup in ("listbox", "true"):
            await locator.click(timeout=2500)
            await page.wait_for_timeout(350)
            options = normalize_field_options(await page.evaluate(_EXTRACT_OPTIONS_JS, selector))
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
        return options
    except Exception:
        return []


async def enrich_field_from_dom(page: Any, field: FormField) -> dict[str, Any]:
    """Augment a provider field with accessibility and current-value evidence."""
    selector = normalize_css_selector(
        field.selector_hint or (f"#{field.id}" if field.id else f"[name='{field.name}']")
    )
    meta: dict[str, Any] = {
        "placeholder": "",
        "ariaLabel": "",
        "ariaRole": "",
        "hasCurrentValue": False,
        "currentValuePresent": False,
        "options": [],
    }
    if not selector:
        return meta
    try:
        meta = await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return { missing: true };
                const val = ('value' in el) ? String(el.value || '').trim() : '';
                const checked = el.checked === true;
                return {
                    placeholder: el.getAttribute('placeholder') || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    ariaRole: el.getAttribute('role') || el.tagName.toLowerCase(),
                    hasCurrentValue: Boolean(val || checked),
                    currentValuePresent: Boolean(val || checked),
                    type: el.getAttribute('type') || el.tagName.toLowerCase(),
                };
            }""",
            selector,
        )
        dom_options = await extract_dom_field_options(page, selector)
        if dom_options:
            meta["options"] = dom_options
    except Exception:
        pass
    return meta


async def capture_field_screenshot(page: Any, field_id: str, selector: str) -> str | None:
    if not selector:
        return None
    try:
        locator = page.locator(selector).first
        if await locator.count() == 0:
            return None
        path = FIELD_SCREENSHOTS_DIR / f"{field_id}.png"
        await locator.screenshot(path=str(path))
        return str(path)
    except Exception:
        return None


async def build_page_evidence(
    *,
    page: Any,
    form_fields: list[FormField],
    provider: str,
    page_url: str,
    page_text: str = "",
    screenshot_refs: list[str] | None = None,
    capture_field_shots: bool = False,
    max_field_screenshots: int = 10,
) -> dict[str, Any]:
    """Build structured evidence packet for the mapping agent."""
    fields: list[dict[str, Any]] = []
    shots_taken = 0

    for index, field in enumerate(form_fields):
        field_id = _stable_field_id(index, field)
        dom_meta = await enrich_field_from_dom(page, field)
        selector = normalize_css_selector(
        field.selector_hint or (f"#{field.id}" if field.id else f"[name='{field.name}']")
    )

        screenshot_ref = None
        if capture_field_shots and shots_taken < max_field_screenshots and not dom_meta.get("missing"):
            ambiguous = not field.label or field.field_type in ("file", "select-one", "select")
            if ambiguous:
                screenshot_ref = await capture_field_screenshot(page, field_id, selector)
                if screenshot_ref:
                    shots_taken += 1

        field_options = merge_field_options(field.options, dom_meta.get("options"))
        fields.append(
            {
                "fieldId": field_id,
                "index": index,
                "label": field.label,
                "helpText": field.help_text,
                "type": field.field_type,
                "placeholder": dom_meta.get("placeholder", ""),
                "required": field.required,
                "section": field.section,
                "options": field_options[:50],
                "accessibilityName": dom_meta.get("ariaLabel") or field.label,
                "accessibilityRole": dom_meta.get("ariaRole", ""),
                "hasCurrentValue": bool(dom_meta.get("hasCurrentValue")),
                "locatorCandidates": _locator_candidates(field),
                "screenshotRef": screenshot_ref,
            }
        )

    evidence: dict[str, Any] = {
        "pageType": "application_form",
        "provider": provider,
        "pageUrl": page_url,
        "fields": fields,
    }
    if page_text:
        evidence["visiblePageText"] = page_text[:4000]
    if screenshot_refs:
        evidence["pageScreenshotRefs"] = screenshot_refs[:5]
    return evidence
