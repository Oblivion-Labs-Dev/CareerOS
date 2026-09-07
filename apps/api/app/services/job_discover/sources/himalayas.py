"""Himalayas Remote Tech Jobs API Adapter for CareerOS Job Ingestion V2."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.job_discover.sources.base import (
    JobSourceAdapter,
    NormalizedJob,
    SourceRole,
)

logger = logging.getLogger("career_os.job_discover.sources.himalayas")


class HimalayasSource(JobSourceAdapter):
    """Himalayas.app live public JSON API adapter (100k+ remote jobs, structured compensation, no auth required)."""

    id = "himalayas"
    name = "Himalayas Remote Jobs API"
    role = SourceRole.AGGREGATOR
    source_type = "public_api"
    priority = 80

    API_BASE = "https://himalayas.app/jobs/api"

    def supports(self, source_type: str, config: dict[str, Any] | None = None) -> bool:
        return source_type.lower() in ("himalayas", "himalayas_remote")

    async def fetch_jobs(
        self,
        client: httpx.AsyncClient,
        company: str,
        config: dict[str, Any],
        compiled_patterns: list[Any],
        cutoff: datetime,
        role_keys: list[str] | None = None,
    ) -> list[NormalizedJob]:
        from app.services.job_discover.scraper_service import is_recent, matches_title

        start_time = datetime.now(UTC)
        discovered_jobs: list[NormalizedJob] = []

        params: dict[str, Any] = {"limit": 50}
        headers = {
            "User-Agent": "CareerOS-JobIngestion/2.0 (+https://careeros.dev)",
            "Accept": "application/json",
        }

        try:
            resp = await self.execute_request(
                client,
                self.API_BASE,
                params=params,
                headers=headers,
                timeout=15.0,
            )
            if not resp or resp.status_code != 200:
                duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
                self.record_failure(f"Himalayas HTTP {resp.status_code if resp else 'No response'}", duration_ms)
                return []

            data = resp.json()
            raw_jobs = data.get("jobs", []) if isinstance(data, dict) else []

            for item in raw_jobs:
                if not isinstance(item, dict):
                    continue

                title = str(item.get("title") or "").strip()
                if not title or not matches_title(title, compiled_patterns):
                    continue

                pub_date_raw = item.get("pubDate")
                pub_date_str = ""
                if isinstance(pub_date_raw, (int, float)):
                    pub_date_str = datetime.fromtimestamp(pub_date_raw, tz=UTC).isoformat()
                elif isinstance(pub_date_raw, str):
                    pub_date_str = pub_date_raw

                if not is_recent(pub_date_str, cutoff):
                    continue

                comp_name = str(item.get("companyName") or item.get("companySlug") or "Himalayas Employer").strip()
                job_url = str(item.get("applicationLink") or item.get("url") or "")
                guid = str(item.get("guid") or item.get("id") or hash(f"{comp_name}:{title}"))

                # Compensation parsing
                min_sal = item.get("minSalary")
                max_sal = item.get("maxSalary")
                currency = str(item.get("currency") or "USD")
                salary_range = ""
                if min_sal and max_sal:
                    salary_range = f"${min_sal:,.0f} - ${max_sal:,.0f} {currency}"
                elif min_sal:
                    salary_range = f"${min_sal:,.0f}+ {currency}"

                desc = str(item.get("description") or "")
                loc_restrictions = item.get("locationRestrictions", [])
                loc_str = ", ".join(loc_restrictions) if isinstance(loc_restrictions, list) else str(loc_restrictions)
                full_loc = f"Remote ({loc_str})" if loc_str else "Remote"

                discovered_jobs.append(
                    NormalizedJob(
                        id=f"himalayas:{guid}",
                        external_id=guid,
                        company=comp_name.lower().replace(" ", "-"),
                        company_name=comp_name,
                        title=title,
                        location=full_loc,
                        remote=True,
                        remote_status="REMOTE",
                        salary_min=float(min_sal) if min_sal is not None else None,
                        salary_max=float(max_sal) if max_sal is not None else None,
                        salary_currency=currency,
                        salary_range=salary_range,
                        description=desc,
                        employment_type="FULL_TIME",
                        source="himalayas",
                        source_type="public_api",
                        source_priority=80,
                        source_quality=80,
                        source_url=job_url,
                        apply_url=job_url,
                        canonical_url=job_url,
                        first_published=pub_date_str,
                        updated_at=pub_date_str,
                        extraction_method="api",
                    )
                )

            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
            self.record_success(len(discovered_jobs), duration_ms)
            return discovered_jobs

        except Exception as exc:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000.0
            self.record_failure(exc, duration_ms)
            return []
