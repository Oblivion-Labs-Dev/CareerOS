"""GitHub Feed JobSourceAdapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceRole


class GitHubFeedSource(JobSourceAdapter):
    """Ingest jobs from machine-readable GitHub repositories with ETag/304 conditional GET."""

    id = "github_feed"
    name = "GitHub Job Feeds"
    role = SourceRole.DISCOVERY
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
        from app.services.job_discover.scraper_service import is_recent, matches_title, s

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
            if content_encoded:
                raw_bytes = base64.b64decode(content_encoded)
            else:
                # The Contents API only inlines base64 up to 1 MB and returns
                # an empty "content" above that, with no error. The feeds worth
                # ingesting are far larger than that (SimplifyJobs' listings.json
                # is ~14 MB), so an enabled feed silently produced zero jobs.
                # Fall back to the raw download URL it hands us.
                download_url = data.get("download_url")
                if not download_url:
                    self.record_failure(f"No inline content or download_url for {etag_key}")
                    return []
                raw_resp = await self.execute_request(
                    client, download_url, headers={"User-Agent": headers["User-Agent"]}, timeout=60.0
                )
                if not raw_resp or raw_resp.status_code != 200:
                    self.record_failure(
                        f"Raw download HTTP {raw_resp.status_code if raw_resp else 'No response'}"
                    )
                    return []
                raw_bytes = raw_resp.content
            items = json.loads(raw_bytes.decode("utf-8"))

            if not isinstance(items, list):
                return []

            jobs: list[NormalizedJob] = []
            for item in items:
                title = item.get("title") or item.get("role", "")
                if compiled_patterns and not matches_title(title, compiled_patterns):
                    continue

                # These feeds are append-only archives: SimplifyJobs' listings
                # carries ~20k entries of which only ~3k are still open. The
                # adapter ignored both flags, so enabling it would have buried
                # the queue in long-closed postings.
                if item.get("active") is False or item.get("is_visible") is False:
                    continue

                posted_raw = item.get("date_posted") or item.get("date_updated")
                posted_iso = ""
                if isinstance(posted_raw, (int, float)):
                    try:
                        posted_iso = datetime.fromtimestamp(posted_raw, tz=UTC).isoformat()
                    except (ValueError, OSError, OverflowError):
                        posted_iso = ""
                elif isinstance(posted_raw, str):
                    posted_iso = posted_raw
                if cutoff and posted_iso and not is_recent(posted_iso, cutoff):
                    continue

                comp_name = item.get("company_name") or item.get("company", "Unknown Company")
                raw_url = item.get("url") or item.get("link", "")
                item_locations = item.get("locations")
                if isinstance(item_locations, list) and item_locations:
                    loc = ", ".join(str(x) for x in item_locations[:3])
                else:
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
