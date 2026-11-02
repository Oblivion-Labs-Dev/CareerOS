"""Greenhouse public question schema (career-ops greenhouse.ts pattern)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

GH_TYPE_MAP = {
    "input_text": "text",
    "textarea": "textarea",
    "input_file": "file",
    "multi_value_single_select": "select-one",
    "multi_value_multi_select": "select-one",
    "multi_select": "select-one",
    "single_select": "select-one",
    "boolean": "select-one",
}


def parse_greenhouse_url(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        if not re.search(r"(^|\.)greenhouse\.io$", host):
            return None
        match = re.search(r"/([^/]+)/jobs/(\d+)", parsed.path)
        if match:
            return match.group(1), match.group(2)
        for_token = (parse_qs(parsed.query).get("for") or [None])[0]
        job_id = (parse_qs(parsed.query).get("token") or [None])[0]
        if for_token and job_id:
            return str(for_token), str(job_id)
    except Exception:
        return None
    return None


async def fetch_greenhouse_schema(url: str) -> dict[str, dict[str, Any]] | None:
    """Fetch question schema keyed by field name and normalized label."""
    parsed = parse_greenhouse_url(url)
    if not parsed:
        return None
    token, job_id = parsed
    api_url = (
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}"
        f"?questions=true"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(api_url, headers={"Accept": "application/json"})
            if response.status_code != 200:
                return None
            data = response.json()
    except Exception:
        return None

    schema: dict[str, dict[str, Any]] = {}
    for question in data.get("questions") or []:
        label = re.sub(r"\s*\*+\s*$", "", str(question.get("label") or "")).strip()
        required = bool(question.get("required"))
        for field in question.get("fields") or []:
            name = str(field.get("name") or "").strip()
            if not name:
                continue
            options = [
                str(value.get("label") or "").strip()
                for value in field.get("values") or []
                if str(value.get("label") or "").strip()
            ]
            entry = {
                "label": label or name,
                "fieldType": GH_TYPE_MAP.get(str(field.get("type") or ""), "text"),
                "required": required,
                "options": options,
            }
            schema[name] = entry
            if label:
                schema[f"label:{label.lower()}"] = entry
    return schema or None


def enrich_field_from_schema(
    *,
    field_id: str,
    label: str,
    field_type: str,
    options: list[str],
    schema: dict[str, dict[str, Any]] | None,
) -> tuple[str, str, list[str], bool]:
    """Merge API schema into a scraped field when DOM extraction is thin."""
    if not schema:
        return label, field_type, options, False

    entry = schema.get(field_id) or schema.get(f"label:{label.lower().strip()}")
    if not entry:
        return label, field_type, options, False

    merged_label = str(entry.get("label") or label)
    merged_type = str(entry.get("fieldType") or field_type)
    api_options = [str(item) for item in entry.get("options") or [] if str(item)]
    merged_options = api_options if len(api_options) > len(options) else options
    if merged_type == "select-one" and not merged_options and api_options:
        merged_options = api_options
    return merged_label, merged_type, merged_options, True
