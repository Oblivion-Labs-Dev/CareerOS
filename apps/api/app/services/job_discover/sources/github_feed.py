"""GitHub Feed JobSourceAdapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob


class GitHubFeedSource(JobSourceAdapter):
    """Ingest jobs from machine-readable GitHub repositories with ETag/304 conditional GET."""

    id = "github_feed"
    name = "GitHub Job Feeds"
    source_type = "github_feed"
    priority = 70
    supports_incremental_sync = True

    def __init__(self) -> None:
        super().__init__()
        self._etags: dict[str, str] = {}

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("github", "github_feed", "github_jobs")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title, s

        start_time = time.perf_counter()
        cfg = config or {}
        owner = cfg.get("owner", "SimplifyJobs")
        repo = cfg.get("repo", "New-Grad-Positions")
        path = cfg.get("path", "listings.json")

        # Disabled by default unless explicitly enabled in config
        if not cfg.get("enabled", False):
            return []

        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "CareerOS-JobIngestion/2.0",
        }
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        etag_key = f"{owner}/{repo}/{path}"
        if etag_key in self._etags:
            headers["If-None-Match"] = self._etags[etag_key]

        resp = await self.execute_request(client, url, headers=headers, timeout=20.0)
        if not resp:
            self.record_failure("GitHub request failed")
            return []

        # 304 Not Modified — cheap, zero data churn
        if resp.status_code == 304:
            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(0, duration)
            return []

        if resp.status_code != 200:
            self.record_failure(f"HTTP {resp.status_code}")
            return []

        # Cache new ETag
        if "ETag" in resp.headers:
            self._etags[etag_key] = resp.headers["ETag"]

        try:
            data = resp.json()
            content_encoded = data.get("content", "")
            raw_bytes = base64.b64decode(content_encoded)
            items = json.loads(raw_bytes.decode("utf-8"))

            if not isinstance(items, list):
                return []

            jobs: list[NormalizedJob] = []
            for item in items:
                title = item.get("title") or item.get("role", "")
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue

                comp_name = item.get("company_name") or item.get("company", "Unknown Company")
                raw_url = item.get("url") or item.get("link", "")
                loc = item.get("location", "United States")

                item_id = s(item.get("id") or item.get("uuid") or hash(raw_url))
                is_remote = any(k in f"{loc} {title}".lower() for k in ("remote", "virtual", "wfh"))
                is_hybrid = "hybrid" in f"{loc} {title}".lower()
                remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

                normalized = NormalizedJob(
                    id=f"ghfeed:{item_id}",
                    external_id=item_id,
                    company=comp_name.lower().replace(" ", "-"),
                    company_name=comp_name,
                    title=title,
                    location=loc,
                    locations=[loc],
                    remote=is_remote,
                    hybrid=is_hybrid,
                    remote_status=remote_status,
                    source_url=raw_url,
                    apply_url=raw_url,
                    canonical_url=raw_url,
                    description="",
                    source="github_feed",
                    source_type="github_feed",
                    source_priority=70,
                    source_quality=70,
                    extraction_method="github_contents_api",
                    provenance_sources=[f"github:{owner}/{repo}"],
                    source_metadata={
                        "repo": f"{owner}/{repo}",
                        "sponsorship": item.get("sponsorship"),
                    },
                )
                jobs.append(normalized)

            duration = (time.perf_counter() - start_time) * 1000
            self.record_success(len(jobs), duration)
            return jobs
        except Exception as exc:
            self.record_failure(exc)
            return []
