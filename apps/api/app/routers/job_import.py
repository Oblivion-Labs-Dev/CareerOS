"""Batch job ingestion for external discovery systems (e.g. SUTRA Manthan).

``POST /api/jobs/import/batch`` feeds jobs into the same pipeline a scrape uses
(``job_discover.store.import_jobs_batch``): normalization, relevancy scoring,
the scraper's DedupeIndex, retention pruning and the discovery snapshot, from
which the queue preprocessor scores and enqueues them like any scraped job.

Authentication is a bearer token read from ``CAREEROS_IMPORT_API_TOKEN``,
compared in constant time. The endpoint is disabled (503) while no token is
configured, and it sits outside the browser session gate (see
``middleware/auth.py``) because the caller is another system, not a person;
the token is its only credential and grants nothing but this import.
"""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import settings

router = APIRouter()

#: Largest batch accepted in one request; a caller with more sends several.
MAX_IMPORT_BATCH = 500


class ImportedJob(BaseModel):
    """One job as sent by the external system."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source: str = Field(min_length=1, max_length=100)
    external_id: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=300)
    url: str = Field(min_length=1, max_length=2000)
    description: str | None = Field(default=None, max_length=100_000)
    posted_at: datetime | None = None
    discovered_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if not value.lower().startswith(("http://", "https://")):
            raise ValueError("must be an http(s) URL")
        return value


class ImportBatchRequest(BaseModel):
    # Validated one job at a time below, so a malformed job is reported as
    # invalid instead of rejecting the whole request.
    jobs: list[Any] = Field(default_factory=list)


def require_import_token(request: Request) -> None:
    expected = settings.careeros_import_api_token
    if not expected:
        raise HTTPException(status_code=503, detail="Job import is disabled until CAREEROS_IMPORT_API_TOKEN is set")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing import token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _as_scraped_job(job: ImportedJob) -> dict[str, Any]:
    """The field names the scraper normalizer (`_normalize_scraped_job`) reads."""
    posted = job.posted_at.isoformat() if job.posted_at else None
    return {
        "source": job.source,
        "externalId": job.external_id or "",
        "title": job.title,
        "company": job.company,
        "location": job.location or "",
        "url": job.url,
        "description": job.description or "",
        "posting_date": posted,
        "updated_at": posted or "",
        "first_seen_at": job.discovered_at.isoformat() if job.discovered_at else None,
    }


def _validation_reason(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'job'}: {error['msg']}" for error in exc.errors()
    )


@router.post("/api/jobs/import/batch", dependencies=[Depends(require_import_token)])
async def import_jobs_batch_route(payload: ImportBatchRequest) -> dict[str, Any]:
    from app.db.store import session_scope
    from app.services.job_discover.store import import_jobs_batch

    if len(payload.jobs) > MAX_IMPORT_BATCH:
        raise HTTPException(status_code=413, detail=f"At most {MAX_IMPORT_BATCH} jobs per batch")

    results: list[dict[str, Any]] = [{} for _ in payload.jobs]
    positions: list[int] = []
    valid: list[ImportedJob] = []
    for position, item in enumerate(payload.jobs):
        try:
            job = ImportedJob.model_validate(item)
        except ValidationError as exc:
            external = item.get("external_id") if isinstance(item, dict) else None
            results[position] = {
                "index": position, "externalId": external, "status": "invalid",
                "jobId": None, "reason": _validation_reason(exc),
            }
            continue
        positions.append(position)
        valid.append(job)

    if valid:
        with session_scope() as db:
            imported = await import_jobs_batch(db, [_as_scraped_job(job) for job in valid])
        for position, job, outcome in zip(positions, valid, imported):
            results[position] = {"index": position, "externalId": job.external_id, **outcome}

    summary = {key: 0 for key in ("created", "existing", "updated", "invalid", "failed")}
    for result in results:
        summary[result["status"]] = summary.get(result["status"], 0) + 1
    return {"success": True, "summary": {**summary, "total": len(results)}, "results": results}
