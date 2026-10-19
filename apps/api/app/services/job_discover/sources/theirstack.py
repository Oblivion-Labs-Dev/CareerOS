"""TheirStack job-postings aggregator adapter for CareerOS Job Ingestion V2.

TheirStack indexes 250M+ job postings across 362k sources (Indeed, LinkedIn,
Glassdoor, Greenhouse, Workable, YC, ...) since 2021. It is a commercial API
whose free signup grants a one-time allowance of ~1,000-1,500 API credits
(1 credit per job returned) — after that it is a paid product.

That one-time nature means this adapter is built as a *self-limiting* source
rather than a recurring feed: a persisted lifetime counter stops it the moment
the configured allowance (`THEIRSTACK_TOTAL_CREDITS`, default 900 for
headroom) is spent, no restarts can resurrect it silently, and it stays free
of cost either way. Its best use is backfilling employers whose ATS offers no
keyless API (via company_name_or down the line); day-to-day coverage comes
from the free adapters.

Inert unless `THEIRSTACK_API_KEY` is configured. Free-tier rate limits
(10 req/min) are respected by issuing a single bounded POST per scrape run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceRole

logger = logging.getLogger("career_os.job_discover.sources.theirstack")

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "job_discover"
QUOTA_FILE = DATA_DIR / "theirstack_quota.json"

# Lifetime job-credit allowance we will spend before refusing to run again
# (TheirStack credits are one-time and paid afterwards). Kept below the
# signup allowance so there is headroom left, and raise it only on a paid
# plan or a deliberate decision to spend the allowance here.
TOTAL_CREDIT_BUDGET = int(os.environ.get("THEIRSTACK_TOTAL_CREDITS", "900"))
DEFAULT_LIMIT = int(os.environ.get("THEIRSTACK_JOB_LIMIT", "50"))
MAX_AGE_DAYS = int(os.environ.get("THEIRSTACK_MAX_AGE_DAYS", "21"))

API_BASE = "https://api.theirstack.com/v1/jobs/search"

# Keyword patterns for TheirStack's job_title_or. Keep the list short: every
# returned row consumes a credit, and the shared title filter still governs
# admission into the queue.
DEFAULT_TITLE_TERMS = (
    "AI Engineer",
    "Machine Learning Engineer",
    "AI Product Manager",
    "Product Manager",
)


def _key() -> str:
    return os.environ.get("THEIRSTACK_API_KEY", "").strip()


def parse_response(payload: Any) -> list[dict[str, Any]]:
    """Pull the `data` array (documented shape) defensively."""
    if isinstance(payload, dict):
        rows = payload.get("data")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


class TheirStackSource(JobSourceAdapter):
    """Broad-source aggregator of employer postings, applied to via resolved URLs."""

    id = "theirstack"
    name = "TheirStack (362k sources)"
    role = SourceRole.AGGREGATOR
    source_type = "aggregator"
    priority = 55

    def __init__(self) -> None:
        super().__init__()
        self.api_key = _key()
        self.enabled = bool(self.api_key)

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("theirstack",)

    # ── persisted lifetime credit ledger (TheirStack credits are one-time) ──

    def _load_quota(self) -> dict[str, int]:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if QUOTA_FILE.is_file():
            try:
                return json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"credits_spent": 0}

    def _save_quota(self, quota: dict[str, int]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        QUOTA_FILE.write_text(json.dumps(quota, indent=2), encoding="utf-8")

    def _remaining_credits(self) -> int:
        quota = self._load_quota()
        return max(0, TOTAL_CREDIT_BUDGET - int(quota.get("credits_spent", 0)))

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title

        start_time = time.perf_counter()
        if not self.api_key:
            return []

        remaining = self._remaining_credits()
        if remaining <= 0:
            logger.info(
                "TheirStack credit budget spent (%d lifetime jobs); skipping pull",
                TOTAL_CREDIT_BUDGET,
            )
            self.record_success(0, 0.0)
            return []

        cfg = config or {}
        limit = int(cfg.get("limit") or DEFAULT_LIMIT)
        limit = max(1, min(limit, remaining))  # can never over-spend a run

        max_age_days = MAX_AGE_DAYS
        if cutoff is not None:
            max_age_days = min(max_age_days, max(1, (datetime.now(UTC) - cutoff).days + 1))

        body: dict[str, Any] = {
            "job_title_or": list(cfg.get("titleTerms") or DEFAULT_TITLE_TERMS),
            "job_country_code_or": ["US"],
            "posted_at_max_age_days": max_age_days,
            "limit": limit,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        resp = await self.execute_request(
            client, API_BASE, method="POST", headers=headers, json_data=body, timeout=40.0
        )
        if not resp or resp.status_code != 200:
            self.record_failure(
                f"HTTP {resp.status_code if resp else 'no response'}",
                (time.perf_counter() - start_time) * 1000,
            )
            return []

        rows = parse_response(resp.json())

        credits_spent = len(rows)  # 1 credit per job returned
        quota = self._load_quota()
        quota["credits_spent"] = int(quota.get("credits_spent", 0)) + credits_spent
        self._save_quota(quota)

        jobs: list[NormalizedJob] = []
        for row in rows:
            title = str(row.get("job_title") or "").strip()
            if not title:
                continue
            if compiled_patterns and not matches_title(title, compiled_patterns):
                continue
            if row.get("is_closed"):
                continue
            if row.get("has_blurred_data"):
                # Preview/blurred rows carry incomplete employer data; never
                # spend a persisted credit entry on them.
                continue

            company_obj = row.get("company_object") if isinstance(row.get("company_object"), dict) else {}
            company_name = (
                str(company_obj.get("name") or "").strip()
                or str(row.get("company") or "").strip()
                or "Unknown Company"
            )
            domain = str(company_obj.get("domain") or row.get("company_domain") or "").strip()

            # Prefer the employer's own career-page URL over a board listing link.
            apply_url = (
                str(row.get("final_url") or "").strip()
                or str(row.get("url") or "").strip()
            )
            if not apply_url:
                continue

            location = (
                str(row.get("short_location") or "").strip()
                or str(row.get("long_location") or "").strip()
                or str(row.get("location") or "").strip()
            )
            is_remote = bool(row.get("remote"))
            is_hybrid = bool(row.get("hybrid"))
            remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

            min_usd = row.get("min_annual_salary_usd")
            max_usd = row.get("max_annual_salary_usd")
            salary_range = (
                f"${int(min_usd)}-${int(max_usd)} USD"
                if isinstance(min_usd, (int, float)) and isinstance(max_usd, (int, float))
                else str(row.get("salary_string") or "")
            )

            statuses = row.get("employment_statuses")
            employment_type = "FULL_TIME"
            if isinstance(statuses, list) and statuses:
                text = " ".join(str(s) for s in statuses)
                if "part" in text.lower():
                    employment_type = "PART_TIME"

            jobs.append(
                NormalizedJob(
                    id=f"theirstack:{row.get('id') or hashlib.sha1(apply_url.encode()).hexdigest()[:16]}",
                    external_id=str(row.get("id") or apply_url),
                    company=company_name.lower().replace(" ", "-"),
                    company_name=company_name,
                    title=title,
                    location=location,
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    source_url=apply_url,
                    apply_url=apply_url,
                    canonical_url=apply_url,
                    description=str(row.get("description") or "")[:20000],
                    updated_at=str(row.get("discovered_at") or ""),
                    first_published=str(row.get("date_posted") or ""),
                    employment_type=employment_type,
                    salary_range=salary_range,
                    source="theirstack",
                    source_type="aggregator",
                    source_priority=self.priority,
                    extraction_method="theirstack",
                    provenance_sources=["theirstack"],
                    source_metadata={
                        "sourceUrl": row.get("source_url") or "",
                        "companyDomain": domain,
                        "easyApply": bool(row.get("easy_apply")),
                        "reposted": bool(row.get("reposted")),
                        "creditsSpent": credits_spent,
                    },
                )
            )

        duration = (time.perf_counter() - start_time) * 1000
        self.record_success(len(jobs), duration)
        return jobs
