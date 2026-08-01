"""Normalize and merge ATS dropdown option lists."""

from __future__ import annotations

import re
from typing import Any

_PHONE_COUNTRY_OPTION_RE = re.compile(r"^.+\s\+\d{1,4}$")


def normalize_field_options(options: list[Any] | None) -> list[str]:
    """Dedupe and drop placeholder entries from ATS dropdown options."""
    seen: set[str] = set()
    cleaned: list[str] = []
    skip_prefixes = ("select", "choose", "please select", "--")
    for raw in options or []:
        opt = str(raw or "").strip()
        if not opt:
            continue
        lower = opt.lower()
        if lower in seen:
            continue
        if any(lower.startswith(prefix) for prefix in skip_prefixes):
            continue
        seen.add(lower)
        cleaned.append(opt)
    return cleaned


def looks_like_phone_country_options(options: list[str]) -> bool:
    """True when options look like intl-tel-input country lists, not real field choices."""
    if len(options) < 5:
        return False
    matches = sum(1 for opt in options if _PHONE_COUNTRY_OPTION_RE.match(opt.strip()))
    return matches >= max(3, int(len(options) * 0.6))


def sanitize_options_for_field(field: dict[str, Any], options: list[Any] | None) -> list[str]:
    """Drop leaked phone-country dropdown options from unrelated fields."""
    cleaned = normalize_field_options(options)
    if not cleaned:
        return cleaned

    from app.services.application_assistant.answer_classification import is_phone_country_field

    label = str(field.get("label") or "")
    if (
        looks_like_phone_country_options(cleaned)
        and not is_phone_country_field(
            label,
            name=str(field.get("name") or ""),
            field_id=str(field.get("fieldId") or field.get("id") or ""),
            selector_hint=str(field.get("selectorHint") or ""),
        )
        and str(field.get("normalizedKey") or "") != "phone_country"
    ):
        return []
    return cleaned


def merge_field_options(*option_lists: list[Any] | None) -> list[str]:
    merged: list[str] = []
    for options in option_lists:
        merged.extend(normalize_field_options(options))
    return normalize_field_options(merged)
