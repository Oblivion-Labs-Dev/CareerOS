"""Fantastic.jobs ATS aggregator adapter for CareerOS Job Ingestion V2.

Fantastic.jobs indexes 3M+ jobs/month straight from the career pages of
200,000+ employers across 58 ATS platforms (Greenhouse, Lever, Workday, Ashby,
iCIMS, ...), refreshed hourly. It is a commercial API whose free plan gives
~500 job credits and ~50 API requests per month/week — enough for one
US-wide AI-role pull per day, at $0.

Every returned ATS job row carries the employer's own apply URL
(job-boards.greenhouse.io/..., jobs.ashbyhq.com/...), so listings need no
redirect resolution and dedupe cleanly against the same postings scraped
from the ATS directly (cross_source_deduplicate rule 5).

Inert unless `FANTASTIC_JOBS_API_KEY` is configured. Two persisted guards keep
the free allowance intact across restarts: a monthly job-credit counter and a
weekly API-request counter. Raise the env vars only for a paid plan.
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

logger = logging.getLogger("career_os.job_discover.sources.fantasticjobs")

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "job_discover"
QUOTA_FILE = DATA_DIR / "fantastic_quota.json"

# Free plan: 500 job credits/month (1 per returned job) and 50 API
# requests/week (1 per call, success or failure). Defaults sit just under
# both ceilings so headroom is never spent by us.
MONTHLY_JOBS_QUOTA = int(os.environ.get("FANTASTIC_JOBS_MONTHLY_JOBS", "500"))
WEEKLY_REQUEST_QUOTA = int(os.environ.get("FANTASTIC_JOBS_WEEKLY_REQUESTS", "45"))
MAX_JOBS_PER_RUN = int(os.environ.get("FANTASTIC_JOBS_MAX_JOBS_PER_RUN", "100"))

API_BASE = "https://data.fantastic.jobs/v1/active-ats"

# Each element is one Jobs credit, so this is a deliberately short,
# high-yield OR list; the shared title filter still governs admission.
DEFAULT_TITLE_QUERY = (
    '"AI Engineer" OR "Machine Learning Engineer" '
    'OR "AI Product Manager" OR "Product Manager"'
)

# Fantastic's `location` parameter takes full place names ("California,
# United States"); a bare country name is accepted per their docs. Empty
# string disables the server-side location filter entirely (rows are then
# trimmed locally by the shared US filter, but still burn credits).
DEFAULT_LOCATION = "United States"


def _key() -> str:
    return os.environ.get("FANTASTIC_JOBS_API_KEY", "").strip()


def parse_ats_rows(payload: Any) -> list[dict[str, Any]]:
    """Accept either the documented shape (a bare JSON array of rows) or the
    defensive {"data": [...]} wrapper, and return only object rows."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("data")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


class FantasticJobsSource(JobSourceAdapter):
    """Employer-ATS aggregator with the employer's own apply links (keyed, free tier)."""

    id = "fantasticjobs"
    name = "Fantastic.jobs (employer career pages)"
    role = SourceRole.AGGREGATOR
    source_type = "aggregator"
    priority = 65

    def __init__(self) -> None:
        super().__init__()
        self.api_key = _key()
        self.enabled = bool(self.api_key)

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("fantasticjobs", "fantastic_jobs")

    # ── persisted quota (jobs credits/month + API requests/week) ──

    def _empty_quota(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "month": now.strftime("%Y-%m"),
            "monthly_jobs": 0,
            "week": now.strftime("%G-W%V"),
            "weekly_requests": 0,
        }

    def _load_quota(self) -> dict[str, Any]:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if QUOTA_FILE.is_file():
            try:
                return json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return self._empty_quota()

    def _save_quota(self, quota: dict[str, Any]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        QUOTA_FILE.write_text(json.dumps(quota, indent=2), encoding="utf-8")

    def _refresh_quota(self, quota: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(UTC)
        if quota.get("month") != now.strftime("%Y-%m"):
            quota["month"] = now.strftime("%Y-%m")
            quota["monthly_jobs"] = 0
        week = now.strftime("%G-W%V")
        if quota.get("week") != week:
            quota["week"] = week
            quota["weekly_requests"] = 0
        return quota

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

        quota = self._refresh_quota(self._load_quota())

        if quota["monthly_jobs"] >= MONTHLY_JOBS_QUOTA:
            logger.info(
                "Fantastic.jobs monthly job quota reached (%d/%d); skipping pull",
                quota["monthly_jobs"], MONTHLY_JOBS_QUOTA,
            )
            self.record_success(0, 0.0)
            return []
        if quota["weekly_requests"] >= WEEKLY_REQUEST_QUOTA:
            logger.info(
                "Fantastic.jobs weekly request quota reached (%d/%d); skipping pull",
                quota["weekly_requests"], WEEKLY_REQUEST_QUOTA,
            )
            self.record_success(0, 0.0)
            return []

        cfg = config or {}
        title_query = cfg.get("titleQuery") or DEFAULT_TITLE_QUERY
        # Server-side location filter: reduces wasted job credits on non-US
        # rows. Omit the parameter entirely when configured as empty.
        location = str(cfg.get("location", DEFAULT_LOCATION)).strip()
        limit = min(MAX_JOBS_PER_RUN, MONTHLY_JOBS_QUOTA - quota["monthly_jobs"])

        params: dict[str, Any] = {
            "time_frame": "24h",
            "limit": limit,
            "title": title_query,
            "description_format": "text",
        }
        if location:
            params["location"] = location

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        resp = await self.execute_request(client, API_BASE, headers=headers, params=params, timeout=40.0)
        quota["weekly_requests"] += 1  # the call consumed a request either way
        if not resp or resp.status_code != 200:
            logger.warning("Fantastic.jobs HTTP %s", resp.status_code if resp else "no response")
            self.record_failure(f"HTTP {resp.status_code if resp else 'no response'}", (time.perf_counter() - start_time) * 1000)
            self._save_quota(quota)
            return []

        rows = parse_ats_rows(resp.json())
        jobs: list[NormalizedJob] = []
        for row in rows:
            title = str(row.get("title") or "").strip()
            org = str(row.get("organization") or "").strip()
            url = str(row.get("url") or "").strip()
            if not title or not url:
                continue
            if compiled_patterns and not matches_title(title, compiled_patterns):
                continue

            # locations_derived holds ready-to-use strings; the raw `locations`
            # fallback holds schema.org Place objects — pull their locality.
            raw_locations = row.get("locations_derived") or row.get("locations") or []
            locations: list[str] = []
            for loc in raw_locations:
                if isinstance(loc, dict):
                    loc = (loc.get("address") or {}).get("addressLocality") or ""
                if loc:
                    locations.append(str(loc))

            work_text = f"{'; '.join(locations)} {row.get('ai_work_arrangement') or ''}".lower()
            date_posted = str(row.get("date_posted") or "").strip()
            date_created = str(row.get("date_created") or "").strip()

            jobs.append(
                NormalizedJob(
                    id=f"fantasticjobs:{row.get('id') or hashlib.sha1(url.encode()).hexdigest()[:16]}",
                    external_id=str(row.get("id") or url),
                    company=org.lower().replace(" ", "-") if org else "unknown-company",
                    company_name=org or "Unknown Company",
                    title=title,
                    location="; ".join(locations[:4]),
                    remote="remote" in work_text,
                    source="fantasticjobs",
                    source_type="aggregator",
                    source_priority=self.priority,
                    source_url=url,
                    apply_url=url,
                    canonical_url=url,
                    employment_type="FULL_TIME",
                    updated_at=date_created,
                    first_published=date_posted,
                    description=str(row.get("description") or row.get("description_html") or "")[:20000],
                    extraction_method="fantastic_ats",
                    provenance_sources=["fantasticjobs", str(row.get("source") or "ats")],
                    source_metadata={
                        "ats": row.get("source"),
                        "atsSlug": row.get("source_slug"),
                        "domain": row.get("domain_derived"),
                        "workArrangement": row.get("ai_work_arrangement") or "",
                    },
                )
            )

        # Account each returned row: Fantastic bills 1 job credit per row,
        # whether or not it survives the local title filter.
        quota["monthly_jobs"] += len(rows)
        self._save_quota(quota)

        duration = (time.perf_counter() - start_time) * 1000
        self.record_success(len(jobs), duration)
        return jobs
