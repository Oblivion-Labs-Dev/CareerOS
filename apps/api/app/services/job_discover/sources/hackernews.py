"""Hacker News 'Who is Hiring?' JobSourceAdapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import html
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import JobSourceAdapter, NormalizedJob, SourceRole


class HackerNewsSource(JobSourceAdapter):
    """Ingest high-signal startup and remote jobs from Hacker News 'Who is Hiring?' threads."""

    id = "hackernews"
    name = "Hacker News (Who is Hiring?)"
    role = SourceRole.DISCOVERY
    source_type = "community"
    priority = 70
    supports_incremental_sync = True

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("hackernews", "hn", "hn_hiring")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str = "all",
        config: dict[str, Any] | None = None,
        compiled_patterns: list[Any] | None = None,
        cutoff: datetime | None = None,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import matches_title, strip_html

        start_time = time.perf_counter()

        # Step 1: Find latest "Ask HN: Who is hiring?" story.
        #
        # This must use search_by_date, not search. Algolia's /search endpoint
        # ranks by RELEVANCE, and its top hit for this query is a one-off 2020
        # thread ("Ask HN: Who is hiring right now?") — so the adapter was
        # faithfully parsing a six-year-old thread every run, and every posting
        # it produced was then dropped by the freshness cutoff.
        search_url = (
            "https://hn.algolia.com/api/v1/search_by_date"
            "?tags=story,author_whoishiring&query=Who%20is%20hiring&hitsPerPage=5"
        )
        resp = await self.execute_request(client, search_url, timeout=15.0)
        if not resp or resp.status_code != 200:
            self.record_failure("Failed to find latest Who is Hiring story")
            return []

        hits = resp.json().get("hits", [])
        # whoishiring posts "Who is hiring?" and "Who wants to be hired?" in the
        # same minute; only the former lists employers.
        story = next(
            (h for h in hits if "who is hiring" in str(h.get("title") or "").lower()),
            None,
        )
        if not story:
            self.record_failure("No Who is Hiring story found")
            return []

        story_id = story.get("objectID")
        story_created = story.get("created_at", "")

        # Step 2: Fetch thread comments
        item_url = f"https://hn.algolia.com/api/v1/items/{story_id}"
        item_resp = await self.execute_request(client, item_url, timeout=25.0)
        if not item_resp or item_resp.status_code != 200:
            self.record_failure(f"Failed to fetch comments for story {story_id}")
            return []

        comments = item_resp.json().get("children", [])
        jobs: list[NormalizedJob] = []

        url_regex = re.compile(r'https?://[^\s<>"\'\)]+')
        email_regex = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

        for comment in comments:
            raw_text = comment.get("text") or ""
            if not raw_text or len(raw_text) < 40:
                continue

            clean_text = strip_html(html.unescape(raw_text)).strip()
            lines = [l.strip() for l in clean_text.splitlines() if l.strip()]
            if not lines:
                continue

            first_line = lines[0]
            # Standard HN header: Company | Role | Location | Remote/Visa | Compensation
            parts = [p.strip() for p in re.split(r"\s*[|•;]\s*", first_line)]
            if len(parts) < 2:
                continue

            company_candidate = re.sub(r"\s*\((?:YC|Techstars|500|W\d+|S\d+)[^)]*\)", "", parts[0], flags=re.I).strip() or parts[0].strip()
            role_candidate = parts[1] if len(parts) > 1 else ""

            # If the role isn't matched by compiled patterns, check full header
            matched_title = role_candidate
            if compiled_patterns:
                if not matches_title(role_candidate, compiled_patterns):
                    if not matches_title(first_line, compiled_patterns):
                        continue
                    # Found title inside header line
                    matched_title = first_line

            location_candidate = "United States"
            if len(parts) >= 3:
                location_candidate = parts[2]

            full_comment_lower = clean_text.lower()
            is_remote = any(k in full_comment_lower for k in ("remote", "virtual", "wfh", "telecommute"))
            is_hybrid = "hybrid" in full_comment_lower
            remote_status = "REMOTE" if is_remote else ("HYBRID" if is_hybrid else "ONSITE")

            # Extract URLs & emails
            links = url_regex.findall(clean_text)
            emails = email_regex.findall(clean_text)
            apply_url = links[0] if links else (f"mailto:{emails[0]}" if emails else f"https://news.ycombinator.com/item?id={comment.get('id')}")
            hn_item_url = f"https://news.ycombinator.com/item?id={comment.get('id')}"

            # Salary extraction
            salary_range = ""
            salary_min = None
            salary_max = None
            sal_match = re.search(r"\$\s*\d{2,3}(?:[kK]|,\d{3})(?:\s*[-–to]+\s*\$?\s*\d{2,3}(?:[kK]|,\d{3}))?", clean_text)
            if sal_match:
                salary_range = sal_match.group(0).strip()
                nums_k = re.findall(r"\b(\d{2,3})[kK]\b", salary_range)
                if nums_k:
                    vals = [float(n) * 1000 for n in nums_k]
                    if len(vals) >= 2:
                        salary_min, salary_max = min(vals[:2]), max(vals[:2])
                    elif len(vals) == 1:
                        salary_min = vals[0]
                else:
                    nums = [float(n.replace(",", "")) for n in re.findall(r"\b\d{2,3}(?:,\d{3})+\b", salary_range)]
                    if len(nums) >= 2:
                        salary_min, salary_max = min(nums[:2]), max(nums[:2])
                    elif len(nums) == 1:
                        salary_min = nums[0]

            # Visa / sponsorship evidence
            sponsorship_mention = any(k in full_comment_lower for k in ("visa", "sponsor", "h-1b", "h1b"))
            sponsorship_status = "yes" if ("visa sponsorship" in full_comment_lower or "will sponsor" in full_comment_lower) else ("no" if "no visa" in full_comment_lower or "cannot sponsor" in full_comment_lower else None)

            comment_id = str(comment.get("id"))
            normalized = NormalizedJob(
                id=f"hn:{comment_id}",
                external_id=comment_id,
                company=company_candidate,
                company_name=company_candidate,
                title=matched_title[:100],
                location=location_candidate[:80],
                locations=[location_candidate[:80]],
                remote=is_remote,
                hybrid=is_hybrid,
                remote_status=remote_status,
                source_url=hn_item_url,
                apply_url=apply_url,
                canonical_url=apply_url if links else hn_item_url,
                description=clean_text[:4000],
                updated_at=comment.get("created_at") or story_created,
                first_published=comment.get("created_at") or story_created,
                employment_type="Full-time",
                salary_range=salary_range,
                salary_min=salary_min,
                salary_max=salary_max,
                source="hackernews",
                source_type="community",
                source_priority=70,
                source_quality=70,
                extraction_method="hn_algolia_api",
                provenance_sources=["hackernews"],
                sponsorship_mention=sponsorship_mention,
                sponsorship_status=sponsorship_status,
                source_metadata={
                    "hn_comment_id": comment.get("id"),
                    "hn_story_id": story_id,
                    "hn_author": comment.get("author"),
                },
            )
            jobs.append(normalized)

        duration = (time.perf_counter() - start_time) * 1000
        self.record_success(len(jobs), duration)
        return jobs
