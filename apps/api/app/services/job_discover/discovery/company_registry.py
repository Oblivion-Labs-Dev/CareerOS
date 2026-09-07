"""Job Source Discovery Service, ATS Fingerprinter, and Centralized Company Registry for CareerOS Job Ingestion V2."""

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
    """Detection result for company ATS identification."""

    provider: str
    confidence: float
    board_identifier: str = ""
    evidence: str = ""
    source_config: dict[str, Any] = field(default_factory=dict)

    @property
    def detected_source(self) -> str:
        """Backward compatibility for existing callers."""
        return self.provider

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "confidence": self.confidence,
            "boardIdentifier": self.board_identifier,
            "evidence": self.evidence,
            "sourceConfig": self.source_config,
        }


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
    """Deterministic ATS detection and fingerprinting without LLM dependencies."""

    @staticmethod
    def fingerprint_ats(url: str, html: str | None = None) -> dict[str, Any]:
        """Deterministic ATS detection returning {provider, confidence, boardIdentifier, evidence}."""
        if not url:
            return {
                "provider": "unknown",
                "confidence": 0.0,
                "boardIdentifier": "",
                "evidence": "Empty URL provided",
            }

        parsed = urlparse(url.lower())
        netloc = parsed.netloc
        path = parsed.path
        parts = [p for p in path.split("/") if p]

        # 1. Greenhouse
        if "boards.greenhouse.io" in netloc or "job-boards.greenhouse.io" in netloc or "greenhouse.io" in netloc:
            board_id = parts[1] if len(parts) >= 2 and parts[0] in ("embed", "v1") else (parts[0] if parts else "")
            return {
                "provider": "greenhouse",
                "confidence": 0.99,
                "boardIdentifier": board_id,
                "evidence": f"URL hostname matches Greenhouse domain with board '{board_id}'",
            }

        # 2. Lever
        if "jobs.lever.co" in netloc or "lever.co" in netloc:
            slug = parts[0] if parts else ""
            return {
                "provider": "lever",
                "confidence": 0.99,
                "boardIdentifier": slug,
                "evidence": f"URL hostname matches Lever domain with slug '{slug}'",
            }

        # 3. Ashby
        if "jobs.ashbyhq.com" in netloc or "ashbyhq.com" in netloc:
            slug = parts[0] if parts else ""
            return {
                "provider": "ashby",
                "confidence": 0.99,
                "boardIdentifier": slug,
                "evidence": f"URL hostname matches Ashby domain with slug '{slug}'",
            }

        # 4. Workday
        if "myworkdayjobs.com" in netloc:
            company_tenant = netloc.split(".")[0]
            site = parts[0] if parts else "careers"
            return {
                "provider": "workday",
                "confidence": 0.98,
                "boardIdentifier": f"{company_tenant}/{site}",
                "evidence": f"Workday tenant '{company_tenant}' host '{netloc}' site '{site}'",
            }

        # 5. SmartRecruiters
        if "smartrecruiters.com" in netloc:
            slug = parts[0] if parts else ""
            return {
                "provider": "smartrecruiters",
                "confidence": 0.99,
                "boardIdentifier": slug,
                "evidence": f"URL hostname matches SmartRecruiters domain with slug '{slug}'",
            }

        # 6. Workable
        if "workable.com" in netloc or "apply.workable.com" in netloc:
            slug = parts[0] if parts else ""
            return {
                "provider": "workable",
                "confidence": 0.98,
                "boardIdentifier": slug,
                "evidence": f"URL hostname matches Workable domain with slug '{slug}'",
            }

        # 7. Recruitee
        if "recruitee.com" in netloc:
            slug = netloc.split(".")[0] if netloc != "recruitee.com" else (parts[0] if parts else "")
            return {
                "provider": "recruitee",
                "confidence": 0.98,
                "boardIdentifier": slug,
                "evidence": f"Recruitee sub-domain match for '{slug}'",
            }

        # 8. BambooHR
        if "bamboohr.com" in netloc:
            portal = netloc.split(".")[0]
            return {
                "provider": "bamboohr",
                "confidence": 0.95,
                "boardIdentifier": portal,
                "evidence": f"BambooHR portal '{portal}'",
            }

        # 9. BreezyHR
        if "breezy.hr" in netloc:
            slug = netloc.split(".")[0] if netloc != "breezy.hr" else (parts[0] if parts else "")
            return {
                "provider": "breezyhr",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"BreezyHR company domain '{slug}'",
            }

        # 10. Personio
        if "personio.com" in netloc or "personio.de" in netloc:
            slug = netloc.split(".")[0]
            return {
                "provider": "personio",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Personio company career board '{slug}'",
            }

        # 11. Teamtailor
        if "teamtailor.com" in netloc:
            slug = netloc.split(".")[0]
            return {
                "provider": "teamtailor",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Teamtailor company board '{slug}'",
            }

        # 12. iCIMS
        if "icims.com" in netloc:
            sub = netloc.split(".")[0]
            portal = sub.replace("careers-", "").replace("jobs-", "")
            return {
                "provider": "icims",
                "confidence": 0.96,
                "boardIdentifier": portal,
                "evidence": f"iCIMS client portal '{portal}'",
            }

        # 13. Oracle Recruiting Cloud / Taleo
        if "oraclecloud.com" in netloc or "taleo.net" in netloc:
            site = "jobsearch"
            if "sites" in parts:
                idx = parts.index("sites")
                if idx + 1 < len(parts):
                    site = parts[idx + 1]
            return {
                "provider": "oracle",
                "confidence": 0.95,
                "boardIdentifier": f"{netloc}:{site}",
                "evidence": f"Oracle Cloud HCM site '{site}' on '{netloc}'",
            }

        # 14. SAP SuccessFactors
        if "successfactors.com" in netloc:
            slug = parts[0] if parts else netloc.split(".")[0]
            return {
                "provider": "successfactors",
                "confidence": 0.92,
                "boardIdentifier": slug,
                "evidence": f"SAP SuccessFactors career portal '{slug}'",
            }

        # 15. Eightfold
        if "eightfold.ai" in netloc:
            slug = parts[0] if parts else netloc.split(".")[0]
            return {
                "provider": "eightfold",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Eightfold AI careers portal '{slug}'",
            }

        # 16. Phenom
        if "phenompeople.com" in netloc or "phenom.com" in netloc:
            slug = parts[0] if parts else netloc.split(".")[0]
            return {
                "provider": "phenom",
                "confidence": 0.92,
                "boardIdentifier": slug,
                "evidence": f"Phenom career experience '{slug}'",
            }

        # 17. Jobvite
        if "jobvite.com" in netloc:
            slug = parts[0] if parts else ""
            return {
                "provider": "jobvite",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Jobvite board '{slug}'",
            }

        # 18. JazzHR
        if "applytojob.com" in netloc:
            slug = netloc.split(".")[0]
            return {
                "provider": "jazzhr",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"JazzHR portal '{slug}'",
            }

        # 19. Comeet
        if "comeet.com" in netloc:
            slug = parts[1] if len(parts) >= 2 and parts[0] == "jobs" else (parts[0] if parts else "")
            return {
                "provider": "comeet",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Comeet employer board '{slug}'",
            }

        # 20. Pinpoint
        if "pinpointhq.com" in netloc:
            slug = netloc.split(".")[0]
            return {
                "provider": "pinpoint",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Pinpoint HQ company board '{slug}'",
            }

        # 21. Rippling Recruiting
        if "rippling-ats.com" in netloc or ("rippling.com" in netloc and "ats" in path):
            slug = parts[-1] if parts else netloc.split(".")[0]
            return {
                "provider": "rippling",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Rippling ATS career page '{slug}'",
            }

        # 22. Gem
        if "gem.com" in netloc:
            slug = parts[1] if len(parts) >= 2 and parts[0] in ("jobs", "careers") else (parts[0] if parts else "")
            return {
                "provider": "gem",
                "confidence": 0.95,
                "boardIdentifier": slug,
                "evidence": f"Gem job board '{slug}'",
            }

        # 23. Direct Big Tech Career Portals
        if "careers.google.com" in netloc:
            return {"provider": "bigtech", "confidence": 0.99, "boardIdentifier": "google", "evidence": "Google Careers Portal"}
        if "amazon.jobs" in netloc:
            return {"provider": "bigtech", "confidence": 0.99, "boardIdentifier": "amazon", "evidence": "Amazon Jobs Portal"}
        if "metacareers.com" in netloc:
            return {"provider": "bigtech", "confidence": 0.99, "boardIdentifier": "meta", "evidence": "Meta Careers Portal"}
        if "jobs.apple.com" in netloc:
            return {"provider": "bigtech", "confidence": 0.99, "boardIdentifier": "apple", "evidence": "Apple Jobs Portal"}
        if "careers.microsoft.com" in netloc:
            return {"provider": "bigtech", "confidence": 0.99, "boardIdentifier": "microsoft", "evidence": "Microsoft Careers Portal"}

        # HTML inspection fallback if provided
        if html:
            html_lower = html.lower()
            if "boards.greenhouse.io" in html_lower or "greenhouse-jobs" in html_lower:
                gh_for = re.search(r'(?:for=|(?:boards\.greenhouse\.io/embed/job_board(?:\.js)?\?for=))([a-z0-9_-]+)', html_lower)
                if gh_for:
                    slug = gh_for.group(1)
                else:
                    gh_m = re.search(r'boards\.greenhouse\.io/([a-z0-9_-]+)', html_lower)
                    slug = gh_m.group(1) if gh_m and gh_m.group(1) != "embed" else ""
                return {"provider": "greenhouse", "confidence": 0.93, "boardIdentifier": slug, "evidence": "Greenhouse embed in HTML"}

            if "jobs.lever.co" in html_lower:
                lev_m = re.search(r'jobs\.lever\.co/([a-z0-9_-]+)', html_lower)
                slug = lev_m.group(1) if lev_m else ""
                return {"provider": "lever", "confidence": 0.93, "boardIdentifier": slug, "evidence": "Lever script/link in HTML"}

            if "jobs.ashbyhq.com" in html_lower or "ashby-job-board" in html_lower:
                ash_m = re.search(r'jobs\.ashbyhq\.com/([a-z0-9_-]+)', html_lower)
                slug = ash_m.group(1) if ash_m else ""
                return {"provider": "ashby", "confidence": 0.93, "boardIdentifier": slug, "evidence": "Ashby embed/link in HTML"}

            if "myworkdayjobs.com" in html_lower:
                wd_m = re.search(r'([a-z0-9_-]+\.wd\d+\.myworkdayjobs\.com)/([a-z0-9_-]+)', html_lower)
                if wd_m:
                    return {
                        "provider": "workday",
                        "confidence": 0.90,
                        "boardIdentifier": f"{wd_m.group(1)}/{wd_m.group(2)}",
                        "evidence": f"Workday iframe/link in HTML: {wd_m.group(1)}",
                    }

            if "smartrecruiters.com" in html_lower:
                sr_m = re.search(r'smartrecruiters\.com/([a-z0-9_-]+)', html_lower)
                slug = sr_m.group(1) if sr_m else ""
                return {"provider": "smartrecruiters", "confidence": 0.90, "boardIdentifier": slug, "evidence": "SmartRecruiters script in HTML"}

            if "application/ld+json" in html_lower and "jobposting" in html_lower:
                return {"provider": "structured_career_page", "confidence": 0.85, "boardIdentifier": url, "evidence": "Schema.org/JobPosting JSON-LD found in HTML"}

        return {
            "provider": "structured_career_page",
            "confidence": 0.50,
            "boardIdentifier": url,
            "evidence": "Generic career page fallback (Schema.org / sitemap)",
        }

    @classmethod
    def detect_from_url(cls, careers_url: str) -> DiscoveryResult | None:
        """Evaluate URL pattern match returning DiscoveryResult."""
        fp = cls.fingerprint_ats(careers_url)
        provider = fp["provider"]
        if provider == "unknown" or (provider == "structured_career_page" and fp["confidence"] < 0.8):
            return None

        # Format source_config
        slug = fp["boardIdentifier"]
        cfg: dict[str, Any] = {"slug": slug}
        if provider == "greenhouse":
            cfg = {"boardId": slug, "slug": slug}
        elif provider == "workday":
            parts = slug.split("/")
            cfg = {"host": parts[0] if parts else "", "company": parts[0].split(".")[0] if parts else "", "board": parts[1] if len(parts) > 1 else "careers"}
        elif provider == "icims":
            cfg = {"portal": slug}
        elif provider == "oracle":
            parts = slug.split(":")
            cfg = {"host": parts[0] if parts else "", "site": parts[1] if len(parts) > 1 else "jobsearch"}
        elif provider == "bamboohr":
            cfg = {"company": slug}
        elif provider == "bigtech":
            cfg = {"company": slug}

        return DiscoveryResult(
            provider=provider,
            confidence=fp["confidence"],
            board_identifier=slug,
            evidence=fp["evidence"],
            source_config=cfg,
        )

    @classmethod
    async def discover_source(cls, client: httpx.AsyncClient, company: str, careers_url: str) -> DiscoveryResult:
        """Full discovery: URL inspection -> HTTP probe -> HTML fingerprinting."""
        # 1. Direct URL pattern match
        url_match = cls.detect_from_url(careers_url)
        if url_match:
            return url_match

        # 2. Fetch page HTML and follow redirects
        try:
            resp = await client.get(careers_url, timeout=12, follow_redirects=True)
            if resp.status_code == 200:
                final_url = str(resp.url)
                if final_url != careers_url:
                    redirect_match = cls.detect_from_url(final_url)
                    if redirect_match:
                        return redirect_match

                # 3. HTML fingerprint
                fp = cls.fingerprint_ats(final_url, html=resp.text)
                slug = fp["boardIdentifier"]
                cfg: dict[str, Any] = {"slug": slug, "careersUrl": final_url}
                if fp["provider"] == "greenhouse":
                    cfg = {"boardId": slug, "slug": slug}
                elif fp["provider"] == "workday":
                    parts = slug.split("/")
                    cfg = {"host": parts[0] if parts else "", "company": parts[0].split(".")[0] if parts else "", "board": parts[1] if len(parts) > 1 else "careers"}

                return DiscoveryResult(
                    provider=fp["provider"],
                    confidence=fp["confidence"],
                    board_identifier=slug,
                    evidence=fp["evidence"],
                    source_config=cfg,
                )
        except Exception as exc:
            return DiscoveryResult(
                provider="structured_career_page",
                confidence=0.40,
                board_identifier=careers_url,
                evidence=f"Fetch failed ({exc}); defaulting to generic structured career page",
                source_config={"careersUrl": careers_url},
            )

        return DiscoveryResult(
            provider="structured_career_page",
            confidence=0.50,
            board_identifier=careers_url,
            evidence="Default structured career page fallback",
            source_config={"careersUrl": careers_url},
        )


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


class CompanyDiscoveryPipeline:
    """End-to-end company discovery workflow:

    Company -> Careers URL Discovery -> ATS Fingerprinting -> ATS Verification -> CompanyRegistry -> Ingestion
    """

    def __init__(self, registry: CompanyRegistry | None = None) -> None:
        self.registry = registry or CompanyRegistry()

    async def discover_and_register_company(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        domain_or_careers_url: str,
    ) -> DiscoveryResult:
        """Resolve company domain/careers URL to verified ATS and persist in registry."""
        careers_url = domain_or_careers_url
        if not careers_url.startswith("http"):
            careers_url = f"https://{domain_or_careers_url}"

        # Standard career subpaths to probe if given root domain
        parsed = urlparse(careers_url)
        if not parsed.path or parsed.path == "/":
            probe_urls = [
                f"{careers_url.rstrip('/')}/careers",
                f"{careers_url.rstrip('/')}/jobs",
                f"https://careers.{parsed.netloc}",
                f"https://jobs.{parsed.netloc}",
                careers_url,
            ]
        else:
            probe_urls = [careers_url]

        best_result: DiscoveryResult | None = None
        for candidate_url in probe_urls:
            res = await JobSourceDiscoveryService.discover_source(client, company_name, candidate_url)
            if res.confidence >= 0.90:
                best_result = res
                break
            if not best_result or res.confidence > best_result.confidence:
                best_result = res

        final_res = best_result or DiscoveryResult(
            provider="structured_career_page",
            confidence=0.50,
            board_identifier=careers_url,
            evidence="Probed candidate URLs, defaulting to structured career page",
            source_config={"careersUrl": careers_url},
        )

        # Register if confidence is sufficient
        if final_res.confidence >= 0.85:
            clean_company = re.sub(r"[^a-zA-Z0-9_-]", "", company_name.lower())
            self.registry.upsert_company(clean_company, final_res.provider, final_res.source_config)

        return final_res
