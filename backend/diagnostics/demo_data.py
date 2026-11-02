"""Detect demo / test fixtures that should not appear on the user dashboard."""

from __future__ import annotations

import re
from typing import Any

_DEMO_COMPANY_NAMES = frozenset(
    {
        "test co",
        "test company",
        "testco",
        "example corp",
        "example company",
        "acme corp",
        "acme",
        "fixture co",
    }
)

_DEMO_JOB_ID_PREFIXES = ("job_test", "test_job")

_DEMO_URL_RE = re.compile(
    r"example\.com|127\.0\.0\.1|localhost|testcompany|/fixtures/",
    re.I,
)


def _normalize_company(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def is_demo_company_name(name: str) -> bool:
    normalized = _normalize_company(name)
    if not normalized:
        return False
    if normalized in _DEMO_COMPANY_NAMES:
        return True
    if normalized.startswith("test co") or normalized.startswith("test company"):
        return True
    return False


def is_demo_application(draft: dict[str, Any]) -> bool:
    if is_demo_company_name(str(draft.get("companyName") or "")):
        return True
    job_id = str(draft.get("jobId") or "").strip().lower()
    if job_id.startswith(_DEMO_JOB_ID_PREFIXES):
        return True
    url = str(draft.get("jobUrl") or draft.get("listingUrl") or "")
    if _DEMO_URL_RE.search(url):
        return True
    return False


def is_demo_job(job: dict[str, Any]) -> bool:
    if is_demo_company_name(str(job.get("company") or "")):
        return True
    job_id = str(job.get("id") or "").strip().lower()
    if job_id.startswith(_DEMO_JOB_ID_PREFIXES):
        return True
    for key in ("applicationUrl", "listingUrl", "url"):
        if _DEMO_URL_RE.search(str(job.get(key) or "")):
            return True
    return False
