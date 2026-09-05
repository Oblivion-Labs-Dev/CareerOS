"""Turn an arbitrary pasted job-posting URL into structured job fields.

Shared by `/jobs/extract` (api.py) and the Application Assistant's "quick add
by link" flow (application_assistant.py) so there's one extraction path, not
two copies that drift apart.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.job_discover.sources.generic_jsonld import parse_jsonld_job_postings

ATS_HOSTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workable.com",
    "smartrecruiters.com",
)


def guess_company_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().removeprefix("www.")
        for ats_host in ATS_HOSTS:
            if host.endswith(ats_host):
                parts = [p for p in parsed.path.split("/") if p]
                if parts:
                    return parts[0].replace("-", " ").replace("_", " ").strip().title()
        return host.split(".")[0].replace("-", " ").title() if host else ""
    except Exception:
        return ""


def _is_safe_public_host(hostname: str) -> bool:
    """Reject localhost/private/link-local targets before a server-side fetch (SSRF guard).

    Only checks the hostname the user pasted, not subsequent redirect hops —
    an accepted tradeoff for this single-user local tool, not a hardened
    multi-tenant fetch proxy.
    """
    if not hostname:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
    except Exception:
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def autoextract_job_from_url(url: str) -> dict[str, Any] | None:
    """Best-effort fetch + Schema.org JobPosting extraction for a pasted job URL.

    Reuses the same JSON-LD parser the career-page crawler uses, so any ATS or
    company careers page that marks up its postings with Schema.org JobPosting
    (Greenhouse, Lever, Ashby, and most standard career sites) resolves for
    free. Returns None if nothing could be extracted, or the URL fails the
    basic SSRF safety check — callers fall back to whatever the user pasted
    in manually (title/company/description), mirroring a plain "paste the JD
    text" flow.
    """
    try:
        hostname = (urlparse(url).hostname or "").lower()
        if not hostname or not _is_safe_public_host(hostname):
            return None
        guessed_company = guess_company_from_url(url) or "company"
        resp = httpx.get(
            url,
            timeout=12,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (CareerOS job import)"},
        )
        if resp.status_code != 200 or not resp.text:
            return None
        jobs = parse_jsonld_job_postings(resp.text, url, guessed_company)
        if not jobs:
            return None
        job = jobs[0]
        return {
            "title": job.title or "",
            "company": job.company_name or guessed_company.title(),
            "location": job.location or "",
            "description": job.description or "",
        }
    except Exception:
        return None
