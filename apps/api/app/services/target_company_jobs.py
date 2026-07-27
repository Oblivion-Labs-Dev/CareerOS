from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.db.store import get_kv, set_kv

CompanyName = Literal["Oracle", "DocuSign"]
LocationFilter = Literal["all", "remote", "washington"]

KV_KEY = "target_company_jobs"
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "target_company_jobs"
ORACLE_SEED_FILE = DATA_DIR / "oracle_seed.json"
DOCUSIGN_JOBS_URL = "https://careers.docusign.com/api/jobs"
ORACLE_JOB_URL = "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch/job/{job_id}"
DOCUSIGN_JOB_URL = "https://careers.docusign.com/careers-home/jobs/{job_id}?lang=en-us&previousLocale=en-US"

SENIOR_KEYWORDS = ("senior", "sr.", "sr ", "staff", "principal")
SOFTWARE_KEYWORDS = ("software", "developer", "engineer", "sde", "platform")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_oracle_seed() -> list[dict[str, Any]]:
    if not ORACLE_SEED_FILE.is_file():
        return []
    return json.loads(ORACLE_SEED_FILE.read_text(encoding="utf-8"))


def _http_get_json(url: str, timeout: int = 25) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "CareerOS/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _url_is_live(url: str, timeout: int = 12) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "CareerOS/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status < 400
    except urllib.error.HTTPError as exc:
        return exc.code < 400
    except urllib.error.URLError:
        return False


def _matches_senior_software(title: str) -> bool:
    lowered = title.lower()
    return any(word in lowered for word in SENIOR_KEYWORDS) and any(word in lowered for word in SOFTWARE_KEYWORDS)


def _location_tags(location: str) -> list[str]:
    lowered = location.lower()
    tags: list[str] = []
    if "remote" in lowered or "flexible" in lowered:
        tags.append("remote")
    if "washington" in lowered or ", wa" in lowered or "seattle" in lowered:
        tags.append("washington")
    if "united states" in lowered or ", us" in lowered:
        tags.append("us")
    return tags


def _normalize_job(
    *,
    company: CompanyName,
    job_id: str,
    title: str,
    location: str,
    url: str,
    active: bool = True,
    source: str = "seed",
) -> dict[str, Any]:
    return {
        "id": job_id,
        "company": company,
        "title": title.strip(),
        "location": location.strip(),
        "url": url.strip(),
        "tags": _location_tags(location),
        "active": active,
        "source": source,
        "lastSeenAt": _utc_now(),
    }


def fetch_docusign_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in range(1, 40):
        payload = _http_get_json(f"{DOCUSIGN_JOBS_URL}?limit=50&page={page}")
        batch = payload.get("jobs") or []
        if not batch:
            break

        new_in_page = 0
        for entry in batch:
            data = entry.get("data") or {}
            req_id = str(data.get("req_id") or data.get("slug") or "").strip()
            if not req_id or req_id in seen:
                continue
            title = str(data.get("title") or "").strip()
            location = str(data.get("location_name") or data.get("country") or "").strip()
            if not _matches_senior_software(title):
                continue
            if data.get("country_code") not in (None, "", "US") and "united states" not in location.lower():
                continue
            if "united states" not in location.lower() and "remote" not in location.lower() and data.get("country_code") != "US":
                if not any(city in location.lower() for city in ("san francisco", "seattle", "chicago", "austin")):
                    continue

            seen.add(req_id)
            new_in_page += 1
            jobs.append(
                _normalize_job(
                    company="DocuSign",
                    job_id=req_id,
                    title=title,
                    location=location or "United States",
                    url=DOCUSIGN_JOB_URL.format(job_id=req_id),
                    source="live-api",
                )
            )

        if new_in_page == 0:
            break

    return jobs


def fetch_oracle_jobs(verify_live: bool = True) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for seed in _load_oracle_seed():
        job_id = str(seed.get("id") or "").strip()
        if not job_id:
            continue
        url = str(seed.get("url") or ORACLE_JOB_URL.format(job_id=job_id))
        active = _url_is_live(url) if verify_live else True
        jobs.append(
            _normalize_job(
                company="Oracle",
                job_id=job_id,
                title=str(seed.get("title") or "Oracle role"),
                location=str(seed.get("location") or "United States"),
                url=url,
                active=active,
                source="seed-verify" if verify_live else "seed",
            )
        )
    return jobs


def refresh_target_company_jobs(*, verify_oracle: bool = True) -> dict[str, Any]:
    docusign = fetch_docusign_jobs()
    oracle = fetch_oracle_jobs(verify_live=verify_oracle)
    jobs = docusign + oracle
    snapshot = {
        "refreshedAt": _utc_now(),
        "companies": {
            "Oracle": {
                "total": len(oracle),
                "active": sum(1 for job in oracle if job["active"]),
                "portalUrl": "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch",
            },
            "DocuSign": {
                "total": len(docusign),
                "active": len(docusign),
                "portalUrl": "https://careers.docusign.com/company/careers",
            },
        },
        "jobs": jobs,
    }
    return snapshot


def get_snapshot(db: Session) -> dict[str, Any]:
    stored = get_kv(db, KV_KEY)
    if stored and isinstance(stored, dict) and stored.get("jobs"):
        return stored
    snapshot = refresh_target_company_jobs()
    set_kv(db, KV_KEY, snapshot)
    return snapshot


def save_snapshot(db: Session, snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot = {**snapshot, "refreshedAt": snapshot.get("refreshedAt") or _utc_now()}
    set_kv(db, KV_KEY, snapshot)
    return snapshot


def refresh_and_store(db: Session, *, verify_oracle: bool = True) -> dict[str, Any]:
    snapshot = refresh_target_company_jobs(verify_oracle=verify_oracle)
    set_kv(db, KV_KEY, snapshot)
    return snapshot


def filter_jobs(
    jobs: list[dict[str, Any]],
    *,
    company: str | None = None,
    location: LocationFilter = "all",
    active_only: bool = True,
) -> list[dict[str, Any]]:
    filtered = jobs
    if company and company.lower() != "all":
        filtered = [job for job in filtered if job.get("company", "").lower() == company.lower()]
    if active_only:
        filtered = [job for job in filtered if job.get("active", True)]
    if location == "remote":
        filtered = [job for job in filtered if "remote" in job.get("tags", [])]
    elif location == "washington":
        filtered = [
            job
            for job in filtered
            if "washington" in job.get("tags", []) or "remote" in job.get("tags", [])
        ]
    return sorted(filtered, key=lambda job: (job.get("company", ""), job.get("title", "")))


def format_whatsapp(jobs: list[dict[str, Any]], *, title: str) -> str:
    lines = [f"*{title}*", ""]
    if not jobs:
        lines.append("_No jobs matched this filter._")
        return "\n".join(lines)

    for index, job in enumerate(jobs, start=1):
        emoji = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟"[index - 1] if index <= 10 else f"{index}."
        lines.extend(
            [
                f"{emoji} *{job.get('title')}*",
                f"🏢 {job.get('company')}",
                f"📍 {job.get('location')}",
                f"🔗 {job.get('url')}",
                "",
            ]
        )
    lines.append(f"_Total: {len(jobs)} roles_")
    return "\n".join(lines).strip()


def merge_oracle_seed_entries(entries: list[dict[str, Any]]) -> None:
    existing = {str(item.get("id")): item for item in _load_oracle_seed()}
    for entry in entries:
        job_id = str(entry.get("id") or "").strip()
        if not job_id:
            continue
        existing[job_id] = {
            "id": job_id,
            "title": str(entry.get("title") or existing.get(job_id, {}).get("title") or "Oracle role"),
            "location": str(entry.get("location") or existing.get(job_id, {}).get("location") or "United States"),
            "url": str(entry.get("url") or ORACLE_JOB_URL.format(job_id=job_id)),
        }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ORACLE_SEED_FILE.write_text(
        json.dumps(list(existing.values()), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def days_since_refresh(snapshot: dict[str, Any]) -> float | None:
    refreshed = snapshot.get("refreshedAt")
    if not refreshed:
        return None
    try:
        parsed = datetime.fromisoformat(str(refreshed).replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        return delta.total_seconds() / 86400
    except ValueError:
        return None


def should_refresh_weekly(snapshot: dict[str, Any]) -> bool:
    age = days_since_refresh(snapshot)
    return age is None or age >= 7
