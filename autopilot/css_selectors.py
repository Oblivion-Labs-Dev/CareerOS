"""CSS selector helpers for Greenhouse/React forms."""

from __future__ import annotations

import re


def normalize_css_selector(selector: str) -> str:
    """
    Convert invalid #id selectors to attribute form.

    Greenhouse often uses numeric element ids (#430), which are invalid in querySelector.
    """
    raw = str(selector or "").strip()
    if not raw:
        return raw
    if not raw.startswith("#"):
        return raw
    el_id = raw[1:]
    if not el_id:
        return raw
    # CSS #id tokens cannot start with a digit; use [id="..."] instead.
    if el_id[0].isdigit() or not re.match(r"^[A-Za-z_-][\w-]*$", el_id):
        escaped = el_id.replace("\\", "\\\\").replace('"', '\\"')
        return f'[id="{escaped}"]'
    return raw
