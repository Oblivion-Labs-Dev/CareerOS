"""Fast AI Jobs (fastaijobs.com) aggregator adapter for CareerOS Job Ingestion V2.

fastaijobs.com is a curated index of openings at AI startups (~37k roles across
~2.3k companies, refreshed daily from the companies' own career pages). Its
role index pages are server-rendered and embed a Schema.org ItemList as
JSON-LD, where each ListItem carries:

    "url":  the employer's canonical ATS apply URL (Greenhouse/Lever/Ashby)
    "name": "{job title} at {company}"

Because the listed URLs already point at the real ATS posting, these rows need
no redirect resolution and dedupe cleanly against the same jobs scraped from
the ATS directly. The pages expose only the 20 most recent roles per role
category, and carry no posting dates, so rows skip the hours cutoff (staleness
is handled by dedup against the dated ATS-side rows).

Free and keyless: plain HTTP GETs of public pages, a handful per scrape run.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.job_discover.sources.base import (
    JobSourceAdapter,
    NormalizedJob,
    SourceRole,
)

logger = logging.getLogger("career_os.job_discover.sources.fastaijobs")

_JSONLD_SCRIPT_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(?P<body>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _find_item_lists(node: Any) -> list[dict]:
    """Recursively collect every ItemList node in a parsed JSON-LD tree.

    fastaijobs currently nests its ItemList inside a top-level ``@graph`` array
    (with CollectionPage and WebSite siblings), but the nesting is an
    implementation detail of their SEO plugin - walking the tree rather than
    pinning one shape keeps the adapter from breaking on a re-theme.
    """
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("@type") == "ItemList":
            found.append(node)
        for value in node.values():
            found.extend(_find_item_lists(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_find_item_lists(value))
    return found


def parse_item_list_jobs(html: str, role_page: str) -> list[tuple[str, str, str]]:
    """Extract (title, company, url) triples from the page's Schema.org ItemList.

    Returns an empty list when the page shape changes or carries no ItemList -
    callers treat that as "this source contributed nothing", matching how the
    rest of the pipeline handles a silent source.
    """
    parsed: list[tuple[str, str, str]] = []
    for match in _JSONLD_SCRIPT_RE.finditer(html):
        try:
            data = json.loads(match.group("body"))
        except (json.JSONDecodeError, TypeError):
            continue
        for item_list in _find_item_lists(data):
            for item in item_list.get("itemListElement") or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                name = str(item.get("name") or "").strip()
                if not url or not name or " at " not in name:
                    continue
                title, company = name.rsplit(" at ", 1)
                title, company = title.strip(), company.strip()
                if title and company:
                    parsed.append((title, company, url))
    if not parsed:
        logger.debug("fastaijobs %s: no ItemList entries found", role_page)
    return parsed


class FastAIJobsSource(JobSourceAdapter):
    """Curated AI-startup job index with direct ATS apply links (free, no auth)."""

    id = "fastaijobs"
    name = "Fast AI Jobs"
    role = SourceRole.AGGREGATOR
    source_type = "aggregator"
    priority = 60

    BASE = "https://www.fastaijobs.com"

    # Role index pages to pull. Kept deliberately short: each page yields the
    # 20 most recent roles and these five cover both target tracks (AI
    # engineering and AI product) plus the adjacent ML-infra roles.
    ROLE_PAGES = (
        "ai-engineer",
        "ml-engineer",
        "product-manager",
        "mlops-infra-engineer",
        "research-engineer",
    )

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("fastaijobs", "fast_ai_jobs")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title

        start_time = datetime.now(UTC)
        discovered: list[NormalizedJob] = []
        seen_urls: set[str] = set()

        headers = {
            "User-Agent": "CareerOS-JobIngestion/2.0 (+https://careeros.dev)",
            "Accept": "text/html",
        }

        try:
            for role_page in self.ROLE_PAGES:
                resp = await self.execute_request(
                    client,
                    f"{self.BASE}/jobs/role/{role_page}",
                    headers=headers,
                    timeout=15.0,
                )
                if not resp or resp.status_code != 200:
                    if not discovered:
                        self.record_failure(
                            f"fastaijobs HTTP {resp.status_code if resp else 'No response'}",
                            (datetime.now(UTC) - start_time).total_seconds() * 1000.0,
                        )
                        return []
                    continue

                for title, comp_name, url in parse_item_list_jobs(resp.text, role_page):
                    if url in seen_urls or not matches_title(title, compiled_patterns):
                        continue
                    seen_urls.add(url)

                    path = urlparse(url).path
                    external_id = path.rsplit("/", 1)[-1] if "/" in path else url

                    discovered.append(
                        NormalizedJob(
                            id=f"fastaijobs:{external_id}",
                            external_id=external_id,
                            company=comp_name.lower().replace(" ", "-"),
                            company_name=comp_name,
                            title=title,
                            location="",  # not carried by the ItemList; unknown passes the US filter
                            employment_type="FULL_TIME",
                            source="fastaijobs",
                            source_type="aggregator",
                            source_priority=self.priority,
                            source_url=url,
                            apply_url=url,
                            canonical_url=url,
                            extraction_method="jsonld",
                            source_metadata={"rolePage": role_page},
                        )
                    )

            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
            self.record_success(len(discovered), duration_ms)
            return discovered

        except Exception as exc:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
            self.record_failure(exc, duration_ms)
            return []
