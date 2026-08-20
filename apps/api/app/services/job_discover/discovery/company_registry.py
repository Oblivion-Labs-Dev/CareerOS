"""Job Source Discovery Service and Centralized Company Registry for CareerOS."""

from __future__ import annotations

import json
from dataclasses import dataclass
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

        return None

    @classmethod
    async def discover_source(cls, client: httpx.AsyncClient, company: str, careers_url: str) -> DiscoveryResult:
        # 1. URL pattern match
        url_match = cls.detect_from_url(careers_url)
        if url_match:
            return url_match

        # 2. Fetch page HTML and check iframe/script links
        try:
            resp = await client.get(careers_url, timeout=10, follow_redirects=True)
            if resp.status_code == 200:
                html = resp.text.lower()
                if "boards.greenhouse.io" in html or "greenhouse" in html:
                    return DiscoveryResult("greenhouse", 0.85, {"slug": company})
                if "jobs.lever.co" in html or "lever" in html:
                    return DiscoveryResult("lever", 0.85, {"slug": company})
                if "ashbyhq.com" in html or "ashby" in html:
                    return DiscoveryResult("ashby", 0.85, {"slug": company})
                if "application/ld+json" in html and "jobposting" in html:
                    return DiscoveryResult("generic_jsonld", 0.80, {"careersUrl": careers_url})
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
