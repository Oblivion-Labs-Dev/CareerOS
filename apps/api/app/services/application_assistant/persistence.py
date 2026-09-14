"""Persistence layer for Application Assistant entities."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy.orm import Session

from app.db.store import (
    EntityStore,
    delete_entity,
    get_entity,
    get_kv,
    list_entities,
    list_entities_by_json_equals,
    new_id,
    now_iso,
    set_kv,
    upsert_entity,
)

logger = logging.getLogger("career_os.application_assistant.persistence")
from app.services.application_assistant.demo_data import is_demo_application, is_demo_job
from app.services.application_assistant.domain import (
    ApplicationStatus,
    DiscoveryRunStatus,
)
from app.services.tracking_email import build_tracking_email

ENTITY_DISCOVERY_RUN = "aa_discovery_run"
ENTITY_DISCOVERED_JOB = "aa_discovered_job"
ENTITY_JOB_MATCH = "aa_job_match"
ENTITY_APPLICATION_DRAFT = "aa_application_draft"
ENTITY_ANSWER_LIBRARY = "aa_answer_library"
ENTITY_BROWSER_RUN = "aa_browser_run"
ENTITY_AUTOPILOT_RUN = "aa_autopilot_run"
ENTITY_AUTOPILOT_JOB = "aa_autopilot_job"
KV_SETTINGS = "application_assistant_settings"

# The Off/Honest/Aggressive resume-optimization dial. Each mode resolves to a
# concrete preset for form-answer inference (allowInferredAnswers + the
# auto-accept/review confidence thresholds already used by field mapping).
# Bullet-level resume tailoring (see services/resume_intelligence/tailoring.py)
# reads this same mode — Off skips rewriting entirely, Honest/Aggressive both
# stay evidence-grounded (the generator never fabricates), differing only in
# phrasing latitude.
# How hard to tailor the resume, and how confident an answer must be before it
# is filled into a form, are two unrelated decisions. They used to ride on one
# setting: choosing "aggressive" tailoring also dropped the auto-accept
# threshold from 0.90 to 0.75 and the review threshold from 0.70 to 0.50, so
# asking for stronger resume wording quietly made the system fill in form
# answers it was far less sure about - on exactly the postings the candidate
# matches worst, since that is when aggressive mode is selected.
#
# Form-answering confidence is now fixed across modes. Tailoring mode governs
# the resume only. Override the thresholds explicitly if they ever need to
# change; they must not move as a side effect of a tailoring choice.
_FORM_ANSWER_CONFIDENCE = {"autoAcceptConfidence": 0.90, "reviewConfidence": 0.70}

TAILORING_MODE_PRESETS: dict[str, dict[str, Any]] = {
    "off": {"allowInferredAnswers": False, **_FORM_ANSWER_CONFIDENCE},
    "honest": {"allowInferredAnswers": True, **_FORM_ANSWER_CONFIDENCE},
    "aggressive": {"allowInferredAnswers": True, **_FORM_ANSWER_CONFIDENCE},
}


def default_settings() -> dict[str, Any]:
    from app.config import settings as app_settings

    return {
        "enabled": True,
        "tailoringMode": "off",
        "allowInferredAnswers": False,
        "llm": {
            "enabled": True,
            "baseUrl": "http://localhost:11434/v1",
            "model": "mistral-small3.2:24b",
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
    mode = settings.get("tailoringMode")
    if mode in TAILORING_MODE_PRESETS:
        preset = TAILORING_MODE_PRESETS[mode]
        merged["allowInferredAnswers"] = preset["allowInferredAnswers"]
        merged["fieldMapping"] = {
            **current.get("fieldMapping", {}),
            **merged.get("fieldMapping", {}),
            "autoAcceptConfidence": preset["autoAcceptConfidence"],
            "reviewConfidence": preset["reviewConfidence"],
        }
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
    try:
        tracking_email = build_tracking_email(payload.get("companyName"), draft_id)
    except Exception:
        tracking_email = None
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
        "trackingEmail": tracking_email,
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


# ── Autopilot Runs & Job Applications ─────────────────────────────────────────

def save_autopilot_run(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    if "id" not in payload:
        payload["id"] = new_id("aprun_")
    if "startedAt" not in payload:
        payload["startedAt"] = now_iso()
    payload["lastHeartbeatAt"] = now_iso()
    return upsert_entity(db, ENTITY_AUTOPILOT_RUN, payload)


def get_autopilot_run(db: Session, run_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_AUTOPILOT_RUN, run_id)


def get_active_autopilot_run(db: Session) -> dict[str, Any] | None:
    runs = list_entities(db, ENTITY_AUTOPILOT_RUN)
    active = [r for r in runs if r.get("status") in ("RUNNING", "PAUSED")]
    if not active:
        return None
    active.sort(key=lambda r: str(r.get("startedAt") or ""), reverse=True)
    return active[0]


AUTOPILOT_JOBS_CACHE_KEY = "autopilot_jobs_all"
AUTOPILOT_STATS_CACHE_KEY = "autopilot_status_company_stats"


def _invalidate_autopilot_jobs_cache() -> None:
    """Drop the cached job list and precomputed stats so the next read rebuilds them.

    The list endpoint serves from a background-refreshed cache, which is fine
    for polling but not for the moment right after the user clicks Apply or
    Mark submitted — they must see their own action immediately, not up to a
    TTL later. Every write goes through save/delete below, so invalidating here
    is enough to keep the user's own changes instant while still absorbing the
    polling load.
    """
    from app.services.read_cache import read_cache

    read_cache.invalidate(AUTOPILOT_JOBS_CACHE_KEY)
    read_cache.invalidate(AUTOPILOT_STATS_CACHE_KEY)


# Statuses a job can sit in where there is still something to do. A duplicate
# record in any of these keeps a posting on a list the user works through, even
# after the application has actually been sent.
_OPEN_AUTOPILOT_STATUSES = (
    "DISCOVERED", "SCORED", "QUEUED", "APPLYING", "STAGED", "NEEDS_REVIEW",
    "MANUAL_REVIEW", "FAILED",
)


def canonical_application_url(url: str | None) -> str:
    """Comparable form of an application URL, ignoring tracking query strings."""
    if not url:
        return ""
    return str(url).split("?")[0].split("#")[0].rstrip("/").strip().lower()


def close_duplicate_applications(db: Session, submitted_job: dict[str, Any]) -> list[str]:
    """Retire other records for a posting that has now been applied to.

    The same posting reaches the queue more than once (re-discovered in a later
    scrape, re-imported by hand, re-queued after an earlier attempt failed), and
    nothing deduplicated the queue by application URL. So submitting one record
    left its siblings sitting in QUEUED/NEEDS_REVIEW, and the posting still
    looked unsubmitted on the list the user works through - which is exactly how
    a manually-completed Okta application read as "not marked as submitted"
    while its own record said SUBMITTED all along.

    Only open statuses are touched; an already-terminal sibling is left alone.
    Returns the ids that were retired.
    """
    raw_url = submitted_job.get("applicationUrl")
    target = canonical_application_url(raw_url)
    if not target:
        return []
    submitted_id = submitted_job.get("id")
    retired: list[str] = []

    # Candidates come from the applicationUrl index where the stored URL matches
    # exactly, which covers the common case of the same posting re-imported. The
    # canonical comparison below still runs, because two records can differ only
    # by a tracking query string and those must still collapse - so when the
    # exact lookup finds nothing, fall back to scanning rather than miss them.
    candidates = list_entities_by_json_equals(
        db, ENTITY_AUTOPILOT_JOB, "$.applicationUrl", raw_url
    )
    if not any(c.get("id") != submitted_id for c in candidates):
        candidates = list_entities(db, ENTITY_AUTOPILOT_JOB)

    for other in candidates:
        if other.get("id") == submitted_id:
            continue
        if other.get("status") not in _OPEN_AUTOPILOT_STATUSES:
            continue
        if canonical_application_url(other.get("applicationUrl")) != target:
            continue
        other["previousStatus"] = other.get("status")
        other["status"] = "INELIGIBLE"
        other["ineligibilityReason"] = "DUPLICATE_APPLICATION"
        other["lastError"] = (
            f"Already applied to this posting (see {submitted_id})"
            if submitted_id
            else "Already applied to this posting"
        )
        other["updatedAt"] = now_iso()
        upsert_entity(db, ENTITY_AUTOPILOT_JOB, other)
        retired.append(str(other.get("id")))
    if retired:
        logger.info(
            "Retired %d duplicate application record(s) for %s", len(retired), target
        )
    return retired


def save_autopilot_job(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    if "id" not in payload:
        payload["id"] = new_id("apjob_")
    if "discoveredAt" not in payload:
        payload["discoveredAt"] = now_iso()

    # A submitted application must not keep carrying the verdict of the attempt
    # that failed before it. Observed live: a DoorDash posting was blocked, then
    # submitted successfully on a retry, and the row ended up reading
    # status=SUBMITTED alongside "reCAPTCHA bot protection blocked the
    # submission" and hasPersistentBlock=true - so the card said submitted while
    # the panel explained why it could not be. The block flag is worse than
    # cosmetic: it keeps the job out of every retry path.
    #
    # This clears at the single funnel every submit path already goes through,
    # rather than at each of the five call sites.
    if payload.get("status") == "SUBMITTED":
        for stale in (
            "ineligibilityReason",
            "ineligibilityDetail",
            "lastError",
            "lastErrorType",
            "skipReason",
        ):
            payload.pop(stale, None)
        payload["hasPersistentBlock"] = False

    saved = upsert_entity(db, ENTITY_AUTOPILOT_JOB, payload)
    # Every path that marks a job submitted - the executor, the assisted-fill
    # hand-off, the "mark submitted" button, the inbox reconciler and the
    # submission watcher - funnels through here, so retiring duplicates at this
    # one point covers all of them instead of five separate call sites.
    if saved.get("status") == "SUBMITTED":
        try:
            close_duplicate_applications(db, saved)
        except Exception:
            logger.exception("Could not retire duplicates for %s", saved.get("id"))
    _invalidate_autopilot_jobs_cache()
    return saved


def get_autopilot_job(db: Session, job_app_id: str) -> dict[str, Any] | None:
    return get_entity(db, ENTITY_AUTOPILOT_JOB, job_app_id)


def delete_autopilot_job(db: Session, job_app_id: str) -> bool:
    deleted = delete_entity(db, ENTITY_AUTOPILOT_JOB, job_app_id)
    _invalidate_autopilot_jobs_cache()
    return deleted



def list_autopilot_jobs(db: Session, status: str | None = None) -> list[dict[str, Any]]:
    """Autopilot jobs, newest first, optionally narrowed to one status.

    A status filter is pushed into SQLite so it resolves through
    ix_entities_status instead of loading every job for the type and comparing
    in Python. Same inputs, same ordering, same output - only the work changes.
    """
    if status:
        jobs = list_entities_by_json_equals(db, ENTITY_AUTOPILOT_JOB, "$.status", status)
    else:
        jobs = list_entities(db, ENTITY_AUTOPILOT_JOB)
    jobs.sort(key=lambda j: str(j.get("queuedAt") or j.get("discoveredAt") or ""), reverse=True)
    return jobs


def get_autopilot_status_company_stats(db: Session) -> dict[str, Any]:
    """Precomputed aggregated counts by status and company.

    Executes a single fast SQLite GROUP BY query instead of pulling and deserializing
    thousands of job payloads in Python.
    """
    from sqlalchemy import text

    query = text("""
        SELECT 
            json_extract(payload, '$.status') as status,
            TRIM(json_extract(payload, '$.company')) as company,
            COUNT(*) as count
        FROM entities 
        WHERE entity_type = 'aa_autopilot_job'
        GROUP BY status, company
    """)
    rows = db.execute(query).fetchall()

    status_counts: dict[str, int] = {}
    company_counts_by_status: dict[str, dict[str, int]] = {
        "all": {},
        "queued": {},
        "submitted": {},
        "review": {},
        "manual": {},
        "failed": {},
        "skipped": {},
        "ineligible": {},
    }

    STATUS_MAP = {
        "QUEUED": "queued",
        "APPLYING": "queued",
        "SUBMITTED": "submitted",
        "NEEDS_REVIEW": "review",
        "STAGED": "review",
        "MANUAL_REVIEW": "manual",
        "FAILED": "failed",
        "SKIPPED": "skipped",
        "INELIGIBLE": "ineligible",
    }

    for st, comp, cnt in rows:
        st = st or "QUEUED"
        comp = comp or "Unknown"
        status_counts[st] = status_counts.get(st, 0) + cnt

        # All
        company_counts_by_status["all"][comp] = company_counts_by_status["all"].get(comp, 0) + cnt

        # By UI bucket
        bucket = STATUS_MAP.get(st)
        if bucket:
            company_counts_by_status[bucket][comp] = company_counts_by_status[bucket].get(comp, 0) + cnt

        # By raw status code
        if st not in company_counts_by_status:
            company_counts_by_status[st] = {}
        company_counts_by_status[st][comp] = company_counts_by_status[st].get(comp, 0) + cnt

    ui_counts = {
        "all": sum(status_counts.values()),
        "submitted": status_counts.get("SUBMITTED", 0),
        "queued": status_counts.get("QUEUED", 0) + status_counts.get("APPLYING", 0),
        "review": status_counts.get("NEEDS_REVIEW", 0) + status_counts.get("STAGED", 0),
        "manual": status_counts.get("MANUAL_REVIEW", 0),
        "failed": status_counts.get("FAILED", 0),
        "skipped": status_counts.get("SKIPPED", 0),
        "ineligible": status_counts.get("INELIGIBLE", 0),
    }

    stats = {
        "statusCounts": status_counts,
        "uiCounts": ui_counts,
        "companyCountsByStatus": company_counts_by_status,
    }
    try:
        set_kv(db, "autopilot_status_company_stats", stats)
    except Exception:
        pass
    return stats


def claim_job_lock(db: Session, job_app_id: str, worker_id: str, lease_seconds: int = 300) -> bool:
    """Take the lease on a job, or return False if another worker holds it.

    The claim is a single conditional UPDATE. It used to read the job, check
    lockedBy, then write in a separate statement - check-then-act, with a window
    in between where a second worker could read the same unlocked row and also
    decide it had won. Both would write their own lock and both would go on to
    submit, which on this system means applying twice to one posting.

    The window is invisible while concurrency is 1, but concurrency is a
    caller-supplied option, so the race was one config change away from being
    real. SQLite serialises writers, so a WHERE clause that re-checks the lock
    makes the claim atomic: exactly one UPDATE matches, and rowcount says who.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, or_, update

    now = now_iso()
    expires_at = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()

    locked_by = func.json_extract(EntityStore.payload, "$.lockedBy")
    lock_expires = func.json_extract(EntityStore.payload, "$.lockExpiresAt")

    statement = (
        update(EntityStore)
        .where(EntityStore.id == job_app_id)
        .where(EntityStore.entity_type == ENTITY_AUTOPILOT_JOB)
        .where(
            or_(
                locked_by.is_(None),          # never locked
                locked_by == "",              # lock explicitly released
                locked_by == worker_id,       # our own lease, being extended
                lock_expires.is_(None),       # locked without an expiry - stale
                lock_expires <= now,          # lease ran out (ISO-8601 sorts)
            )
        )
        .values(
            payload=func.json_set(
                EntityStore.payload,
                "$.lockedBy", worker_id,
                "$.lockedAt", now,
                "$.lockExpiresAt", expires_at,
            )
        )
        .execution_options(synchronize_session=False)
    )

    result = db.execute(statement)
    if not result.rowcount:
        return False
    db.flush()
    _invalidate_autopilot_jobs_cache()
    return True


def release_job_lock(db: Session, job_app_id: str, worker_id: str) -> bool:
    job = get_autopilot_job(db, job_app_id)
    if not job:
        return False
    if job.get("lockedBy") == worker_id:
        job["lockedBy"] = None
        job["lockedAt"] = None
        job["lockExpiresAt"] = None
        upsert_entity(db, ENTITY_AUTOPILOT_JOB, job)
        return True
    return False


def _canonical_url_key(url: str) -> str:
    """Normalize a job application URL to a stable dedup key.

    Strips tracking params, lowercases the netloc, and trims trailing slashes
    so ``https://Company.com/jobs/123?utm_source=foo`` and
    ``https://company.com/jobs/123`` resolve to the same key.
    """
    if not url or not url.strip():
        return ""
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    _TRACKING = frozenset({
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "ref", "referer", "referrer", "gclid", "fbclid", "msclkid", "source",
        "trk", "gh_jid", "gh_src", "lever-source", "ashby_jid",
    })
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    clean_query = {k: v for k, v in query.items() if k.lower() not in _TRACKING}
    return urlunparse((
        parsed.scheme,
        parsed.netloc.lower(),
        parsed.path.rstrip("/"),
        parsed.params,
        urlencode(clean_query, doseq=True),
        "",
    ))


def _composite_job_key(company: str, title: str, app_url: str = "") -> str:
    """Deterministic key from company + title + canonical URL."""
    norm_c = re.sub(r"(inc|llc|corp|corporation|ltd|co)\b", "", company.lower(), flags=re.IGNORECASE)
    norm_c = re.sub(r"[^\w]", "", norm_c).strip()
    norm_t = re.sub(r"[^\w\s]", "", title.lower())
    norm_t = re.sub(r"\s+", " ", norm_t).strip()
    clean_url = _canonical_url_key(app_url)
    if clean_url:
        from urllib.parse import urlparse
        p = urlparse(clean_url)
        url_part = f"{p.netloc}{p.path}".rstrip("/")
        return f"{norm_c}::{norm_t}::{url_part}"
    return f"{norm_c}::{norm_t}"


def is_duplicate_application(
    db: Session,
    company: str,
    title: str,
    application_url: str = "",
    *,
    exclude_statuses: tuple[str, ...] = ("SKIPPED",),
) -> tuple[bool, dict[str, Any] | None]:
    """Check whether a job has already been submitted / queued / staged.

    Returns ``(is_dup, existing_job_or_None)``.

    By default jobs that were explicitly SKIPPED are *not* treated as
    duplicates so the user can re-queue them.
    """
    all_jobs = list_entities(db, ENTITY_AUTOPILOT_JOB)

    # Build lookup sets
    new_url_key = _canonical_url_key(application_url)
    new_composite = _composite_job_key(company, title, application_url)

    for existing in all_jobs:
        ex_status = (existing.get("status") or "").upper()
        if ex_status in exclude_statuses:
            continue

        # URL-based match (highest signal)
        if new_url_key:
            ex_url = _canonical_url_key(existing.get("applicationUrl") or "")
            if ex_url and ex_url == new_url_key:
                return True, existing

        # Composite key match (company + title + URL path)
        ex_composite = _composite_job_key(
            existing.get("company") or "",
            existing.get("title") or "",
            existing.get("applicationUrl") or "",
        )
        if new_composite and new_composite == ex_composite:
            return True, existing

    return False, None


