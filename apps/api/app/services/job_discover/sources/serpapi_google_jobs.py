"""SerpApi Google Jobs JobSourceAdapter for CareerOS Job Ingestion V2."""

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

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob

logger = logging.getLogger("career_os.job_discover.serpapi")

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "job_discover"
CACHE_FILE = DATA_DIR / "serpapi_cache.json"
QUOTA_FILE = DATA_DIR / "serpapi_quota.json"

MONTHLY_FREE_QUOTA = 250
DAILY_REQUEST_BUDGET = 8  # ~240/month max to ensure we never exceed 250


class SerpApiGoogleJobsSource(JobSourceAdapter):
    """Google Jobs aggregator adapter via SerpApi with strict query caching and quota guards."""

    id = "serpapi_google_jobs"
    name = "Google Jobs (SerpApi)"
    source_type = "aggregator"
    priority = 60
    supports_incremental_sync = True

    def __init__(self) -> None:
        super().__init__()
        self.api_key = os.environ.get("SERPAPI_KEY", "")
        if not self.api_key:
            self.enabled = False

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("serpapi", "serpapi_google_jobs", "google_jobs")

    def _load_quota(self) -> dict[str, Any]:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if QUOTA_FILE.is_file():
            try:
                return json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        now = datetime.now(UTC)
        return {
            "month": now.strftime("%Y-%m"),
            "monthly_count": 0,
            "day": now.strftime("%Y-%m-%d"),
            "daily_count": 0,
        }

    def _increment_quota(self) -> bool:
        now = datetime.now(UTC)
        current_month = now.strftime("%Y-%m")
        current_day = now.strftime("%Y-%m-%d")

        quota = self._load_quota()
        if quota.get("month") != current_month:
            quota["month"] = current_month
            quota["monthly_count"] = 0

        if quota.get("day") != current_day:
            quota["day"] = current_day
            quota["daily_count"] = 0

        if quota["monthly_count"] >= MONTHLY_FREE_QUOTA:
            logger.warning("SerpApi monthly quota reached (%d/%d). Skipping call.", quota["monthly_count"], MONTHLY_FREE_QUOTA)
            return False

        if quota["daily_count"] >= DAILY_REQUEST_BUDGET:
            logger.warning("SerpApi daily request budget reached (%d/%d). Skipping call.", quota["daily_count"], DAILY_REQUEST_BUDGET)
            return False

        quota["monthly_count"] += 1
        quota["daily_count"] += 1
        QUOTA_FILE.write_text(json.dumps(quota, indent=2), encoding="utf-8")
        return True

    def _load_cache(self) -> dict[str, Any]:
        if CACHE_FILE.is_file():
            try:
                return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_cache(self, cache: dict[str, Any]) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title, s, strip_html

        start_time = time.perf_counter()
        if not self.api_key:
            return []

        cfg = config or {}
        query = cfg.get("query") or (f"{company} software engineer" if company and company != "all" else "senior software engineer")
        location = cfg.get("location", "United States")

        q_hash = hashlib.sha256(f"{query}:{location}".encode()).hexdigest()[:16]
        cache = self._load_cache()
        cached_entry = cache.get(q_hash)

        now_ts = datetime.now(UTC).timestamp()
        # 12-hour cache TTL
        if cached_entry and (now_ts - cached_entry.get("timestamp", 0)) < 12 * 3600:
            raw_postings = cached_entry.get("results", [])
        else:
            if not self._increment_quota():
                return []

            url = "https://serpapi.com/search.json"
            params = {
                "engine": "google_jobs",
                "q": query,
                "location": location,
                "api_key": self.api_key,
            }

            resp = await self.execute_request(client, url, params=params, timeout=25.0)
            if not resp or resp.status_code != 200:
                self.record_failure(f"HTTP {resp.status_code if resp else 'No response'}")
                return []

            data = resp.json()
            raw_postings = data.get("jobs_results", [])
            cache[q_hash] = {"timestamp": now_ts, "results": raw_postings}
            self._save_cache(cache)

        jobs: list[NormalizedJob] = []
        for item in raw_postings:
            title = item.get("title", "")
            if compiled_patterns and not matches_title(title, compiled_patterns):
                continue

            comp_name = item.get("company_name", "Unknown Company")
            loc = item.get("location", location)
            apply_options = item.get("apply_options") or []
            apply_url = apply_options[0].get("link") if apply_options else item.get("share_link", "")

            # Job ID from job_id or share_link
            job_id = s(item.get("job_id") or hash(apply_url))

            detected_extensions = item.get("detected_extensions", {})
            posted_at = detected_extensions.get("posted_at", "")
            work_from_home = detected_extensions.get("work_from_home", False)
            schedule_type = detected_extensions.get("schedule_type", "Full-time")

            salary_str = detected_extensions.get("salary", "")

            combined = f"{loc} {title}".lower()
            is_remote = work_from_home or any(k in combined for k in ("remote", "virtual", "wfh"))
            is_hybrid = "hybrid" in combined
            remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

            normalized = NormalizedJob(
                id=f"google_jobs:{job_id}",
                external_id=job_id,
                company=comp_name.lower().replace(" ", "-"),
                company_name=comp_name,
                title=title,
                location=loc,
                locations=[loc],
                remote=is_remote,
                hybrid=is_hybrid,
                remote_status=remote_status,
                source_url=apply_url,
                apply_url=apply_url,
                canonical_url=apply_url,
                description=strip_html(item.get("description", "")),
                updated_at="",
                first_published=posted_at,
                employment_type=schedule_type,
                salary_range=salary_str,
                source="google_jobs",
                source_type="aggregator",
                source_priority=60,
                source_quality=60,
                extraction_method="serpapi_google_jobs",
                provenance_sources=["google_jobs"],
                source_metadata={"via": item.get("via", "")},
            )
            jobs.append(normalized)

        duration = (time.perf_counter() - start_time) * 1000
        self.record_success(len(jobs), duration)
        return jobs
