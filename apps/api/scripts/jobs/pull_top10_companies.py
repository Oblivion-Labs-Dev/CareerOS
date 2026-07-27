#!/usr/bin/env python3
"""Pull Senior SWE roles from top 10 target companies (live APIs where available)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.target_company_jobs import (  # noqa: E402
    ORACLE_SEED_FILE,
    _load_oracle_seed,
    _location_tags,
    _matches_senior_software,
    format_whatsapp,
)

GREENHOUSE_BOARDS: dict[str, str] = {
    "Stripe": "stripe",
    "Databricks": "databricks",
    "Anthropic": "anthropic",
    "Airbnb": "airbnb",
}

PORTAL_ONLY: dict[str, str] = {
    "Google": "https://www.google.com/about/careers/applications/jobs/results/?q=Senior%20Software%20Engineer&location=United%20States",
    "Microsoft": "https://careers.microsoft.com/us/en/search-results?keywords=Senior%20Software%20Engineer&location=United%20States",
    "Meta": "https://www.metacareers.com/jobs?q=Senior%20Software%20Engineer&country=US",
}

DOCUSIGN_JOBS_URL = "https://careers.docusign.com/api/jobs"
DOCUSIGN_JOB_URL = "https://careers.docusign.com/careers-home/jobs/{job_id}?lang=en-us"
AMAZON_SEARCH_URL = "https://www.amazon.jobs/en/search.json"


def _http_get_json(url: str, timeout: int = 30) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CareerOS/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _us_location_ok(location: str) -> bool:
    tags = _location_tags(location)
    return "us" in tags or "remote" in tags or "washington" in tags


def fetch_greenhouse(company: str, board: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    payload = _http_get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    for entry in payload.get("jobs") or []:
        title = str(entry.get("title") or "").strip()
        if not _matches_senior_software(title):
            continue
        loc = entry.get("location") or {}
        location = loc.get("name", "") if isinstance(loc, dict) else str(loc)
        if not _us_location_ok(location):
            continue
        jobs.append(
            {
                "company": company,
                "title": title,
                "location": location,
                "url": entry.get("absolute_url") or "",
                "tags": _location_tags(location),
            }
        )
    return jobs


def fetch_amazon() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    offset = 0
    while offset < 300:
        url = (
            f"{AMAZON_SEARCH_URL}?base_query=Senior%20Software%20Engineer"
            f"&country=USA&result_limit=50&offset={offset}"
        )
        payload = _http_get_json(url)
        batch = payload.get("jobs") or []
        if not batch:
            break
        for entry in batch:
            title = str(entry.get("title") or "").strip()
            if not _matches_senior_software(title):
                continue
            city = str(entry.get("city") or "").strip()
            state = str(entry.get("state") or entry.get("state_code") or "").strip()
            location = ", ".join(part for part in (city, state, "USA") if part)
            if entry.get("country_code") != "USA" and not _us_location_ok(location):
                continue
            job_path = str(entry.get("job_path") or "").strip()
            jobs.append(
                {
                    "company": "Amazon",
                    "title": title,
                    "location": location,
                    "url": f"https://www.amazon.jobs{job_path}" if job_path else "",
                    "tags": _location_tags(location),
                }
            )
        offset += len(batch)
        if len(batch) < 50:
            break
    return jobs


def fetch_docusign() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in range(1, 25):
        payload = _http_get_json(f"{DOCUSIGN_JOBS_URL}?limit=50&page={page}")
        batch = payload.get("jobs") or []
        if not batch:
            break
        for entry in batch:
            data = entry.get("data") or {}
            req_id = str(data.get("req_id") or "").strip()
            if not req_id or req_id in seen:
                continue
            title = str(data.get("title") or "").strip()
            location = str(data.get("location_name") or "United States").strip()
            if not _matches_senior_software(title):
                continue
            if data.get("country_code") not in (None, "", "US") and not _us_location_ok(location):
                continue
            seen.add(req_id)
            jobs.append(
                {
                    "company": "DocuSign",
                    "title": title,
                    "location": location,
                    "url": DOCUSIGN_JOB_URL.format(job_id=req_id),
                    "tags": _location_tags(location),
                }
            )
    return jobs


def fetch_oracle() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if not ORACLE_SEED_FILE.is_file():
        return jobs
    for seed in _load_oracle_seed():
        location = str(seed.get("location") or "United States")
        title = str(seed.get("title") or "Oracle role")
        if not _matches_senior_software(title):
            continue
        if not _us_location_ok(location):
            continue
        jobs.append(
            {
                "company": "Oracle",
                "title": title,
                "location": location,
                "url": str(seed.get("url") or ""),
                "tags": _location_tags(location),
            }
        )
    return jobs


def pull_top10(*, location: str = "all") -> dict[str, Any]:
    by_company: dict[str, list[dict[str, Any]]] = {}
    for company, board in GREENHOUSE_BOARDS.items():
        by_company[company] = fetch_greenhouse(company, board)
    by_company["Amazon"] = fetch_amazon()
    by_company["DocuSign"] = fetch_docusign()
    by_company["Oracle"] = fetch_oracle()

    all_jobs: list[dict[str, Any]] = []
    for company in [
        "Google",
        "Microsoft",
        "Amazon",
        "Meta",
        "Stripe",
        "Databricks",
        "Anthropic",
        "Airbnb",
        "Oracle",
        "DocuSign",
    ]:
        all_jobs.extend(by_company.get(company, []))

    if location == "remote":
        all_jobs = [job for job in all_jobs if "remote" in job.get("tags", [])]
    elif location == "washington":
        all_jobs = [
            job
            for job in all_jobs
            if "washington" in job.get("tags", []) or "remote" in job.get("tags", [])
        ]

    return {
        "companies": {
            name: {
                "total": len(by_company.get(name, [])),
                "portalUrl": PORTAL_ONLY.get(name),
                "livePull": name not in PORTAL_ONLY,
            }
            for name in [
                "Google",
                "Microsoft",
                "Amazon",
                "Meta",
                "Stripe",
                "Databricks",
                "Anthropic",
                "Airbnb",
                "Oracle",
                "DocuSign",
            ]
        },
        "jobs": all_jobs,
        "total": len(all_jobs),
        "portalOnly": PORTAL_ONLY,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull top 10 company senior SWE jobs")
    parser.add_argument("--location", default="all", choices=["all", "remote", "washington"])
    parser.add_argument("--whatsapp", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    snapshot = pull_top10(location=args.location)
    companies = snapshot["companies"]

    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return 0

    print("Top 10 target companies - Senior Software Engineer (US)")
    print(f"Filter: {args.location}\n")
    for name in companies:
        meta = companies[name]
        if meta.get("livePull"):
            print(f"  {name:12} {meta['total']:3} roles (live API)")
        else:
            print(f"  {name:12}  -  portal only -> {meta['portalUrl']}")

    print(f"\nLive pull total: {snapshot['total']} roles (excludes Google, Microsoft, Meta)")

    if args.whatsapp:
        print()
        print(format_whatsapp(snapshot["jobs"], title=f"Top 10 target jobs · {args.location}"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
