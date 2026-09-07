"""Job Source Discovery Service and Centralized Company Registry for CareerOS Job Ingestion V2."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "job_discover"
CONFIG_FILE = DATA_DIR / "company_config.json"


@dataclass
class DiscoveryResult:
    detected_source: str
    confidence: float
    source_config: dict[str, Any]


@dataclass
class CompanySource:
    """Rich company source tracking model adhering to Phase 8 specification."""

    company_id: str
    company_name: str
    careers_url: str = ""
    source_type: str = "ats"
    provider: str = "generic"
    board_slug: str = ""
    tenant: str = ""
    site: str = ""
    company_identifier: str = ""
    enabled: bool = True
    discovered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    verified_at: str | None = None
    last_successful_sync_at: str | None = None
    last_failure_at: str | None = None
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JobSourceDiscoveryService:
    """Detect underlying ATS platform from company domain, careers URL, or HTML contents."""

    @staticmethod
    def detect_from_url(careers_url: str) -> DiscoveryResult | None:
        if not careers_url:
            return None

        parsed = urlparse(careers_url.lower())
        netloc = parsed.netloc

        if "greenhouse.io" in netloc or "boards.greenhouse.io" in careers_url:
            parts = [p for p in parsed.path.split("/") if p]
            board_id = parts[1] if len(parts) >= 2 and parts[0] == "embed" else (parts[0] if parts else "")
            return DiscoveryResult("greenhouse", 0.99, {"boardId": board_id, "slug": board_id})

        if "lever.co" in netloc or "jobs.lever.co" in careers_url:
            parts = [p for p in parsed.path.split("/") if p]
            slug = parts[0] if parts else ""
            return DiscoveryResult("lever", 0.99, {"slug": slug})

        if "ashbyhq.com" in netloc or "jobs.ashbyhq.com" in careers_url:
            parts = [p for p in parsed.path.split("/") if p]
            slug = parts[0] if parts else ""
            return DiscoveryResult("ashby", 0.99, {"slug": slug})

        if "myworkdayjobs.com" in netloc:
            # Format: https://company.wd1.myworkdayjobs.com/site
            host = netloc
            parts = [p for p in parsed.path.split("/") if p]
            company_tenant = netloc.split(".")[0]
            site = parts[0] if parts else "careers"
            return DiscoveryResult("workday", 0.95, {"host": host, "company": company_tenant, "board": site})

        if "smartrecruiters.com" in netloc or "jobs.smartrecruiters.com" in careers_url:
            parts = [p for p in parsed.path.split("/") if p]
            slug = parts[0] if parts else ""
            return DiscoveryResult("smartrecruiters", 0.99, {"slug": slug})

        if "workable.com" in netloc or "apply.workable.com" in careers_url:
            parts = [p for p in parsed.path.split("/") if p]
            slug = parts[0] if parts else ""
            return DiscoveryResult("workable", 0.99, {"slug": slug})

        if "icims.com" in netloc:
            parts = netloc.split(".")
            portal = parts[0] if len(parts) >= 3 else ""
            return DiscoveryResult("icims", 0.95, {"portal": portal})

        if "oraclecloud.com" in netloc or "taleo.net" in netloc:
            parts = [p for p in parsed.path.split("/") if p]
            site = "jobsearch"
            if "sites" in parts:
                idx = parts.index("sites")
                if idx + 1 < len(parts):
                    site = parts[idx + 1]
            return DiscoveryResult("oracle", 0.95, {"host": netloc, "site": site})

        if "jobvite.com" in netloc or "jobs.jobvite.com" in careers_url:
            parts = [p for p in parsed.path.split("/") if p]
            slug = parts[0] if parts else ""
            return DiscoveryResult("jobvite", 0.90, {"slug": slug})

        if "bamboohr.com" in netloc:
            portal = netloc.split(".")[0]
            return DiscoveryResult("bamboohr", 0.90, {"company": portal})

        return None

    @classmethod
    async def discover_source(cls, client: httpx.AsyncClient, company: str, careers_url: str) -> DiscoveryResult:
        # 1. URL pattern match
        url_match = cls.detect_from_url(careers_url)
        if url_match:
            return url_match

        # 2. Fetch page HTML and check redirect target or embedded iframe/script links
        try:
            resp = await client.get(careers_url, timeout=12, follow_redirects=True)
            if resp.status_code == 200:
                final_url = str(resp.url)
                if final_url != careers_url:
                    redirect_match = cls.detect_from_url(final_url)
                    if redirect_match:
                        return redirect_match

                html = resp.text.lower()

                # Check iframe embeds or script tags
                gh_match = re.search(r'boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)', html)
                if gh_match:
                    return DiscoveryResult("greenhouse", 0.95, {"slug": gh_match.group(1)})

                lever_match = re.search(r'jobs\.lever\.co/([a-z0-9_-]+)', html)
                if lever_match:
                    return DiscoveryResult("lever", 0.95, {"slug": lever_match.group(1)})

                ashby_match = re.search(r'jobs\.ashbyhq\.com/([a-z0-9_-]+)', html)
                if ashby_match:
                    return DiscoveryResult("ashby", 0.95, {"slug": ashby_match.group(1)})

                sr_match = re.search(r'smartrecruiters\.com/([a-z0-9_-]+)', html)
                if sr_match:
                    return DiscoveryResult("smartrecruiters", 0.90, {"slug": sr_match.group(1)})

                if "myworkdayjobs.com" in html:
                    wd_match = re.search(r'([a-z0-9_-]+\.wd\d+\.myworkdayjobs\.com)/([a-z0-9_-]+)', html)
                    if wd_match:
                        return DiscoveryResult("workday", 0.90, {
                            "host": wd_match.group(1),
                            "company": wd_match.group(1).split(".")[0],
                            "board": wd_match.group(2),
                        })

                if "application/ld+json" in html and "jobposting" in html:
                    return DiscoveryResult("generic_jsonld", 0.85, {"careersUrl": careers_url})
        except Exception:
            pass

        return DiscoveryResult("generic", 0.50, {"careersUrl": careers_url})


class CompanyRegistry:
    """Centralized management for target companies and their ATS configs."""

    def __init__(self, config_path: Path = CONFIG_FILE) -> None:
        self.config_path = config_path

    def load_registry(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def save_registry(self, data: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_companies(self) -> list[dict[str, Any]]:
        reg = self.load_registry()
        result: list[dict[str, Any]] = []
        for source_type, company_map in reg.items():
            if isinstance(company_map, dict):
                for name, cfg in company_map.items():
                    result.append({
                        "company": name,
                        "source": source_type,
                        "config": cfg,
                        "enabled": True,
                    })
        return result

    def upsert_company(self, company: str, source: str, config: dict[str, Any]) -> None:
        reg = self.load_registry()
        if source not in reg:
            reg[source] = {}
        reg[source][company] = config
        self.save_registry(reg)
