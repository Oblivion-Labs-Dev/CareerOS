"""Persistence layer for Application Assistant entities."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.db.store import (
    delete_entity,
    get_entity,
    get_kv,
    list_entities,
    new_id,
    now_iso,
    set_kv,
    upsert_entity,
)
from app.services.application_assistant.demo_data import is_demo_application, is_demo_job
from app.services.application_assistant.domain import (
    ApplicationStatus,
    DiscoveryRunStatus,
)

ENTITY_DISCOVERY_RUN = "aa_discovery_run"
ENTITY_DISCOVERED_JOB = "aa_discovered_job"
ENTITY_JOB_MATCH = "aa_job_match"
ENTITY_APPLICATION_DRAFT = "aa_application_draft"
ENTITY_ANSWER_LIBRARY = "aa_answer_library"
ENTITY_BROWSER_RUN = "aa_browser_run"
KV_SETTINGS = "application_assistant_settings"


def default_settings() -> dict[str, Any]:
    return {
        "enabled": True,
        "allowInferredAnswers": False,
        "llm": {
            "enabled": True,
            "baseUrl": "http://localhost:11434/v1",
            "model": "qwen3:8b",
            "apiKey": "",
            "timeout": 60,
            "maxRetries": 2,
            "confidenceThreshold": 0.7,
            "provider": "ollama",
        },
        "browser": {
            "headed": True,
            "timeout": 60000,
            "profileDir": "",
        },
        "domainAllowlist": [],
        "fieldMapping": {
            "enabled": True,
            "mode": "agent_assisted",
            "includePageText": True,
            "pageTextMaxChars": 4000,
            "mappingModel": "",
            "visionEnabled": False,
            "visionModel": "",
            "autoAcceptConfidence": 0.90,
            "reviewConfidence": 0.70,
            "maxScreenshotFields": 10,
            "fallbackToRules": True,
            "maxFieldsPerRequest": 50,
        },
    }


def get_settings(db: Session) -> dict[str, Any]:
    stored = get_kv(db, KV_SETTINGS)
    if not stored:
        return default_settings()
    defaults = default_settings()
    merged = {**defaults, **stored}
    if "llm" in stored:
        merged["llm"] = {**defaults["llm"], **stored["llm"]}
    if "browser" in stored:
        merged["browser"] = {**defaults["browser"], **stored["browser"]}
    if "fieldMapping" in stored:
        merged["fieldMapping"] = {**defaults["fieldMapping"], **stored["fieldMapping"]}
    return merged


def save_settings(db: Session, settings: dict[str, Any]) -> dict[str, Any]:
    current = get_settings(db)
    merged = {**current, **settings}
    set_kv(db, KV_SETTINGS, merged)
    return merged


# ── Discovery Runs ────────────────────────────────────────────────────────────

def create_discovery_run(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    run = {
        "id": new_id("disc_"),
        "status": DiscoveryRunStatus.PENDING.value,
        "jobsFound": 0,
        "logs": [],
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        **payload,
    }
    return upsert_entity(db, ENTITY_DISCOVERY_RUN, run)


def get_discovery_run(db: Session, run_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_DISCOVERY_RUN, run_id)


def update_discovery_run(db: Session, run_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    current = get_discovery_run(db, run_id)
    if not current:
        return None
    merged = {**current, **patch, "updatedAt": now_iso()}
    return upsert_entity(db, ENTITY_DISCOVERY_RUN, merged)


def list_discovery_runs(db: Session) -> list[dict[str, Any]]:
    return sorted(
        list_entities(db, ENTITY_DISCOVERY_RUN),
        key=lambda r: r.get("createdAt", ""),
        reverse=True,
    )


def append_discovery_log(db: Session, run_id: str, log_entry: dict[str, Any]) -> None:
    run = get_discovery_run(db, run_id)
    if not run:
        return
    logs = run.get("logs", [])
    logs.append(log_entry)
    update_discovery_run(db, run_id, {"logs": logs})


# ── Discovered Jobs ───────────────────────────────────────────────────────────

def upsert_discovered_job(db: Session, job: dict[str, Any]) -> dict[str, Any]:
    if not job.get("id"):
        job["id"] = new_id("job_")
    if not job.get("dateDiscovered"):
        job["dateDiscovered"] = now_iso()
    return upsert_entity(db, ENTITY_DISCOVERED_JOB, job)


def list_discovered_jobs(
    db: Session,
    *,
    discovery_run_id: str | None = None,
    active_only: bool = True,
    exclude_demo: bool = True,
) -> list[dict[str, Any]]:
    jobs = list_entities(db, ENTITY_DISCOVERED_JOB)
    if discovery_run_id:
        jobs = [j for j in jobs if j.get("discoveryRunId") == discovery_run_id]
    if active_only:
        jobs = [j for j in jobs if j.get("active", True)]
    if exclude_demo:
        jobs = [j for j in jobs if not is_demo_job(j)]
    return sorted(jobs, key=lambda j: j.get("dateDiscovered", ""), reverse=True)


def get_discovered_job(db: Session, job_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_DISCOVERED_JOB, job_id)


# ── Job Matches ───────────────────────────────────────────────────────────────

def save_job_match(db: Session, match: dict[str, Any]) -> dict[str, Any]:
    job_id = match.get("jobId", "")
    existing = list_entities(db, ENTITY_JOB_MATCH)
    for m in existing:
        if m.get("jobId") == job_id:
            match["id"] = m["id"]
            break
    if not match.get("id"):
        match["id"] = new_id("match_")
    return upsert_entity(db, ENTITY_JOB_MATCH, match)


def get_job_match(db: Session, job_id: str) -> dict[str, Any] | None:
    for m in list_entities(db, ENTITY_JOB_MATCH):
        if m.get("jobId") == job_id:
            return m
    return None


# ── Application Drafts ────────────────────────────────────────────────────────

_DRAFT_PRESERVE_ON_RECREATE = frozenset({
    "status",
    "progress",
    "fields",
    "verifiedCount",
    "reviewCount",
    "missingCount",
    "conflictingCount",
    "screenshots",
    "errors",
    "browserRunId",
    "createdAt",
    "resumeId",
})


def application_id_for_job(job_id: str) -> str:
    """Stable application id for a discovered job — one job, one application."""
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", str(job_id)).strip("_")
    return f"app_{safe}"[:120]


_STATUS_KEEP_RANK = {
    "in_progress": 6,
    "needs_review": 5,
    "ready_to_prepare": 4,
    "blocked": 3,
    "submitted": 2,
    "archived": 1,
}


def normalize_application_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/").lower()
    query = parse_qs(parsed.query)
    if "gh_jid" in query and query["gh_jid"]:
        return f"{host}{path}?gh_jid={query['gh_jid'][0]}"
    return f"{host}{path}"


def _application_identity_key(draft: dict[str, Any]) -> str:
    job_id = draft.get("jobId")
    if job_id:
        return f"job:{job_id}"
    url_key = normalize_application_url(draft.get("jobUrl"))
    if url_key:
        return f"url:{url_key}"
    return f"id:{draft.get('id')}"


def _application_keep_score(draft: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _STATUS_KEEP_RANK.get(str(draft.get("status") or ""), 0),
        len(draft.get("fields") or []),
        int(draft.get("verifiedCount") or 0),
        draft.get("updatedAt") or "",
    )


def cleanup_duplicate_application_drafts(db: Session) -> int:
    """Remove duplicate drafts for the same job, keeping the most advanced record."""
    drafts = [
        draft
        for draft in list_entities(db, ENTITY_APPLICATION_DRAFT)
        if not is_demo_application(draft)
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for draft in drafts:
        grouped.setdefault(_application_identity_key(draft), []).append(draft)

    removed = 0
    for group in grouped.values():
        if len(group) <= 1:
            continue
        group.sort(key=_application_keep_score, reverse=True)
        keeper_id = str(group[0].get("id") or "")
        for duplicate in group[1:]:
            duplicate_id = str(duplicate.get("id") or "")
            if duplicate_id and duplicate_id != keeper_id:
                if delete_application_draft(db, duplicate_id):
                    removed += 1
    if removed:
        db.flush()
    return removed


def get_application_draft_by_job_id(
    db: Session,
    job_id: str,
    *,
    exclude_demo: bool = True,
) -> dict[str, Any] | None:
    if not job_id:
        return None

    canonical_id = application_id_for_job(job_id)
    direct = get_application_draft(db, canonical_id)
    if direct and (not exclude_demo or not is_demo_application(direct)):
        return direct

    matches: list[dict[str, Any]] = []
    for draft in list_entities(db, ENTITY_APPLICATION_DRAFT):
        if draft.get("jobId") != job_id:
            continue
        if exclude_demo and is_demo_application(draft):
            continue
        matches.append(draft)

    if not matches:
        return None
    return max(matches, key=lambda d: d.get("updatedAt", ""))


def create_application_draft(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = payload.get("jobId")
    existing = get_application_draft_by_job_id(db, job_id, exclude_demo=False) if job_id else None
    if existing:
        metadata_patch = {
            k: v
            for k, v in payload.items()
            if k not in _DRAFT_PRESERVE_ON_RECREATE and k != "id"
        }
        if metadata_patch:
            return update_application_draft(db, existing["id"], metadata_patch) or existing
        return existing

    draft_id = application_id_for_job(job_id) if job_id else new_id("app_")
    draft = {
        "id": draft_id,
        "status": ApplicationStatus.READY_TO_PREPARE.value,
        "progress": 0.0,
        "fields": [],
        "verifiedCount": 0,
        "reviewCount": 0,
        "missingCount": 0,
        "conflictingCount": 0,
        "screenshots": [],
        "errors": [],
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
        **payload,
    }
    draft["id"] = draft_id
    return upsert_entity(db, ENTITY_APPLICATION_DRAFT, draft)


def get_application_draft(db: Session, app_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_APPLICATION_DRAFT, app_id)


def update_application_draft(db: Session, app_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    current = get_application_draft(db, app_id)
    if not current:
        return None
    merged = {**current, **patch, "updatedAt": now_iso()}
    return upsert_entity(db, ENTITY_APPLICATION_DRAFT, merged)


def list_application_drafts(
    db: Session,
    *,
    status: str | None = None,
    exclude_demo: bool = True,
    cleanup_duplicates: bool = False,
) -> list[dict[str, Any]]:
    if cleanup_duplicates:
        cleanup_duplicate_application_drafts(db)
    drafts = list_entities(db, ENTITY_APPLICATION_DRAFT)
    if exclude_demo:
        drafts = [d for d in drafts if not is_demo_application(d)]
    if status:
        drafts = [d for d in drafts if d.get("status") == status]

    by_job_id: dict[str, dict[str, Any]] = {}
    without_job: list[dict[str, Any]] = []
    for draft in drafts:
        job_id = draft.get("jobId")
        if not job_id:
            without_job.append(draft)
            continue
        previous = by_job_id.get(job_id)
        if not previous or draft.get("updatedAt", "") > previous.get("updatedAt", ""):
            by_job_id[job_id] = draft

    drafts = list(by_job_id.values()) + without_job
    return sorted(drafts, key=lambda d: d.get("updatedAt", ""), reverse=True)


def delete_application_draft(db: Session, app_id: str) -> bool:
    """Remove an application draft and its browser runs."""
    if not get_application_draft(db, app_id):
        return False
    for run in list_entities(db, ENTITY_BROWSER_RUN):
        if run.get("applicationId") == app_id and run.get("id"):
            delete_entity(db, ENTITY_BROWSER_RUN, str(run["id"]))
    delete_entity(db, ENTITY_APPLICATION_DRAFT, app_id)
    return True


def purge_demo_applications(db: Session) -> int:
    """Delete test/demo application drafts left over from dev or integration tests."""
    removed = 0
    for draft in list_entities(db, ENTITY_APPLICATION_DRAFT):
        if not is_demo_application(draft):
            continue
        app_id = str(draft.get("id") or "")
        if app_id and delete_application_draft(db, app_id):
            removed += 1
    return removed


def save_application_fields(db: Session, app_id: str, fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    from app.services.application_assistant.answer_classification import count_classifications

    counts = count_classifications(fields)
    total = len(fields) if fields else 1
    progress = (counts["verified"] + counts.get("manual_only", 0)) / total * 100

    return update_application_draft(db, app_id, {
        "fields": fields,
        "verifiedCount": counts["verified"],
        "reviewCount": counts["inferred"],
        "missingCount": counts["unknown"],
        "conflictingCount": counts["conflict"],
        "progress": round(progress, 1),
    })


# ── Answer Library ────────────────────────────────────────────────────────────

def list_answer_library(db: Session) -> list[dict[str, Any]]:
    return list_entities(db, ENTITY_ANSWER_LIBRARY)


def upsert_answer(db: Session, answer: dict[str, Any]) -> dict[str, Any]:
    if not answer.get("id"):
        answer["id"] = new_id("ans_")
        answer["createdAt"] = now_iso()
    answer["updatedAt"] = now_iso()
    return upsert_entity(db, ENTITY_ANSWER_LIBRARY, answer)


def get_answer(db: Session, answer_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_ANSWER_LIBRARY, answer_id)


def delete_answer(db: Session, answer_id: str) -> bool:
    return delete_entity(db, ENTITY_ANSWER_LIBRARY, answer_id)


# ── Browser Runs ──────────────────────────────────────────────────────────────

def create_browser_run(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    run = {
        "id": new_id("brun_"),
        "status": "pending",
        "headed": True,
        "startedAt": now_iso(),
        **payload,
    }
    return upsert_entity(db, ENTITY_BROWSER_RUN, run)


def get_browser_run(db: Session, run_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_BROWSER_RUN, run_id)


def update_browser_run(db: Session, run_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    current = get_browser_run(db, run_id)
    if not current:
        return None
    merged = {**current, **patch}
    return upsert_entity(db, ENTITY_BROWSER_RUN, merged)


def index_active_browser_runs(db: Session) -> dict[str, dict[str, Any]]:
    """Map applicationId -> newest active browser run (single query)."""
    by_app: dict[str, dict[str, Any]] = {}
    for run in list_entities(db, ENTITY_BROWSER_RUN):
        if run.get("status") not in ("pending", "running"):
            continue
        app_id = str(run.get("applicationId") or "")
        if not app_id:
            continue
        previous = by_app.get(app_id)
        if not previous or str(run.get("startedAt") or "") >= str(previous.get("startedAt") or ""):
            by_app[app_id] = run
    return by_app


def get_active_browser_run_for_app(db: Session, app_id: str) -> dict[str, Any] | None:
    for run in list_entities(db, ENTITY_BROWSER_RUN):
        if run.get("applicationId") == app_id and run.get("status") in ("pending", "running"):
            return run
    return None
