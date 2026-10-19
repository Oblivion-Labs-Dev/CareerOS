"""Deterministic HTML form scanner — parses fields from a saved apply page.

Standard-library only (html.parser): no browser, no network, no LLM. Works
offline against recorded/synthetic fixtures and replayed page HTML. It emits
raw field descriptors that ``profile_map`` turns into normalised questions.

This is intentionally conservative: anything it cannot read confidently is
reported as type ``unknown`` and ends up in REVIEW, never in a guess.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

_RAW_TYPES = {
    "text": "text",
    "email": "email",
    "tel": "phone",
    "phone": "phone",
    "textarea": "textarea",
    "select": "select",
    "select-one": "select",
    "checkbox": "checkbox",
    "radio": "radio",
    "file": "file",
    "date": "date",
    "number": "number",
    "url": "text",
}


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: list[dict[str, Any]] = []
        self.labels: dict[str, str] = {}
        self._label_for: str | None = None
        self._label_text: list[str] = []
        self._label_wrapped: list[dict[str, Any]] | None = None
        self._select: dict[str, Any] | None = None
        self._textarea: dict[str, Any] | None = None

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _truthy(attrs: dict[str, str], name: str) -> bool:
        value = attrs.get(name)
        if value is None:
            return False
        return value.strip().lower() in ("", "true", "1", "required", "yes")

    def _label_text_value(self) -> str:
        return " ".join(" ".join(self._label_text).split()).strip()

    # -- tag handlers ---------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs}
        if tag == "label":
            self._label_for = attrs.get("for") or None
            self._label_text = []
            self._label_wrapped = []
            return
        if tag == "input":
            raw_type = (attrs.get("type") or "text").strip().lower()
            if raw_type in ("hidden", "submit", "button", "image", "reset"):
                return
            field = self._make_field(tag, attrs, raw_type)
            if field:
                self.fields.append(field)
                if self._label_wrapped is not None:
                    self._label_wrapped.append(field)
            return
        if tag == "textarea":
            field = self._make_field(tag, attrs, "textarea")
            if field:
                self.fields.append(field)
                if self._label_wrapped is not None:
                    self._label_wrapped.append(field)
                self._textarea = field
            return
        if tag == "select":
            field = self._make_field(tag, attrs, "select")
            if field:
                self.fields.append(field)
                if self._label_wrapped is not None:
                    self._label_wrapped.append(field)
                self._select = field
            return

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            text = self._label_text_value()
            if self._label_for and text:
                self.labels[self._label_for] = text
            if self._label_wrapped is not None and text:
                for field in self._label_wrapped:
                    if not field.get("label"):
                        field["label"] = text
            self._label_for = None
            self._label_text = []
            self._label_wrapped = None
            return
        if tag == "textarea" and self._textarea is not None:
            self._textarea = None
            return
        if tag == "select" and self._select is not None:
            self._select = None

    def handle_data(self, data: str) -> None:
        if self._label_text is not None and (
            self._label_for is not None or self._label_wrapped is not None
        ):
            self._label_text.append(data)

    # -- field construction ---------------------------------------------

    def _make_field(
        self, tag: str, attrs: dict[str, str], raw_type: str
    ) -> dict[str, Any] | None:
        name = attrs.get("name") or attrs.get("id") or ""
        if not name:
            return None
        field: dict[str, Any] = {
            "name": name,
            "id": attrs.get("id") or "",
            "type": _RAW_TYPES.get(raw_type, "unknown"),
            "required": self._truthy(attrs, "required")
            or self._truthy(attrs, "aria-required"),
            "options": [],
            "label": attrs.get("aria-label", "").strip()
            or attrs.get("placeholder", "").strip()
            or attrs.get("data-testid", "").strip(),
        }
        if "data-required" in attrs and not field["required"]:
            field["required"] = self._truthy(attrs, "data-required")
        if field["type"] == "select" and attrs.get("multiple"):
            field["type"] = "select"
        return field


class FormScanner:
    """Parse form fields out of saved apply-page HTML (offline)."""

    def scan(self, html: str) -> list[dict[str, Any]]:
        if not html or "<" not in html:
            return []
        parser = _FormParser()
        try:
            parser.feed(html)
            parser.close()
        except Exception:
            # Hard-fail nothing: unparsable pages simply produce no questions
            # and the caller routes preparation to a fetch/manual path.
            return []
        options_by_name: dict[str, list[str]] = {}
        # Replay option collection pass: html.parser gives us options while a
        # select is open; the parser above appends to _select during
        # handle_data. Simpler second pass keeps logic decoupled:
        options_by_name = _collect_options(html)
        for field in parser.fields:
            label = field.get("label") or parser.labels.get(field["id"] or "") or ""
            if not label:
                label = parser.labels.get(field["name"], "")
            field["label"] = label
            field["options"] = options_by_name.get(field["name"], field["options"])
        return parser.fields


def _collect_options(html: str) -> dict[str, list[str]]:
    """Map select-name -> option labels via a focused option/select pass."""

    parser = _OptionParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return {}
    return parser.options


class _OptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.options: dict[str, list[str]] = {}
        self._current: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = {k: (v or "") for k, v in attrs}
        if tag == "select":
            name = attrs.get("name") or attrs.get("id") or ""
            self._current = name if name else None
        elif tag == "option" and self._current:
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._current:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._current:
            label = " ".join(" ".join(self._buf).split()).strip()
            value = label
            if label:
                bucket = self.options.setdefault(self._current, [])
                if label not in bucket:
                    bucket.append(label)
        elif tag == "select":
            self._current = None


_SCANNER = FormScanner()


def scan_form_fields(html: str | None) -> list[dict[str, Any]]:
    """Public entry: raw, deterministic field descriptors from HTML."""

    if not html:
        return []
    return _SCANNER.scan(html)
