"""Auto Apply Lanes — parallel saved-search configs drawing from one shared
daily cap (Intelligence Layer, CareerOS KV + entities).

Lanes match against the SAME pool the Applications/Autopilot page reads from
(`aa_discovered_job` + `aa_job_match`, via `application_assistant.persistence`
and `application_assistant.job_discovery.filter_jobs` — the exact pure
function `GET /application-assistant/jobs` already uses) — not the separate
`job_discover` module, which only backs the Job Scraper page's own filters
and is a different, currently-empty pool in this environment.

A lane never submits anything itself. Evaluating lanes only:
  (a) filters discovered jobs via the existing `job_discovery.filter_jobs`,
      respecting each lane's match-quality bar, include/exclude keywords,
      location/company text filters, and per-lane cap;
  (b) stages the best matches into the existing application-draft pipeline
      via `create_application_draft` (the same call the quick-add-by-URL and
      scraper-import paths use), tagging which lane staged each one;
  (c) when a lane doesn't require review, actually runs the real Playwright
      prepare step (`execute_application_prepare`) for what it just staged.
      `AutopilotRunner` is deliberately NOT used here: it re-derives its own
      candidate list from the discovered-job pool via its own ranker
      (`job_filter_ranker.filter_and_rank_jobs`) and does not consume
      externally-created drafts, so calling `AutopilotRunner.start()` would
      not reliably touch what a lane just staged. Submission risk/eligibility
      after prepare stays entirely governed by submission_policy/
      submission_guard, same as every other path into this pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import (
    delete_entity,
    get_kv,
    list_entities,
    new_id,
    now_iso,
    patch_entity,
    set_kv,
    upsert_entity,
)
from app.services.application_assistant.job_discovery import filter_jobs as filter_discovered_jobs
from app.services.application_assistant.persistence import (
    create_application_draft,
    get_job_match,
    list_application_drafts,
    list_discovered_jobs,
    update_application_draft,
)

LANE_ENTITY = "auto_apply_lane"
CAP_KEY = "intelligence_auto_apply_shared_cap"
RUN_LOG_KEY = "intelligence_auto_apply_lanes_log"

MAX_ACTIVE_LANES = 5
DEFAULT_DAILY_CAP = 10

DEFAULT_LANE_FILTERS = {
    "includeKeywords": "",
    "excludeKeywords": "",
    "location": "",
    "company": "",
    "freshness": "all",
}

FRESHNESS_HOURS = {"24": 24, "48": 48, "72": 72, "168": 168}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _passes_text_filter(value: str, needle: str) -> bool:
    if not needle:
        return True
    return needle.strip().lower() in (value or "").lower()


def _passes_freshness(job: dict[str, Any], freshness: str) -> bool:
    hours = FRESHNESS_HOURS.get(str(freshness or "all"))
    if not hours:
        return True
    raw = job.get("dateDiscovered") or ""
    try:
        discovered = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    if discovered.tzinfo is None:
        discovered = discovered.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - discovered).total_seconds() / 3600
    return age_hours <= hours


# ── Shared daily cap ─────────────────────────────────────────────────────────

def get_shared_cap(db: Session) -> int:
    stored = get_kv(db, CAP_KEY)
    return int((stored or {}).get("dailyCap") or DEFAULT_DAILY_CAP)


def set_shared_cap(db: Session, daily_cap: int) -> dict[str, Any]:
    daily_cap = max(1, min(200, int(daily_cap)))
    set_kv(db, CAP_KEY, {"dailyCap": daily_cap})
    return {"dailyCap": daily_cap}


def _submitted_today_count(db: Session) -> int:
    """Real submissions today, read from the same `aa_application_draft`
    records Autopilot/Review Center write — never a parallel counter that
    could drift from what actually happened."""
    today = _today()
    count = 0
    for draft in list_application_drafts(db):
        if draft.get("status") != "submitted":
            continue
        ts = str(draft.get("submittedAt") or draft.get("updatedAt") or "")
        if ts.startswith(today):
            count += 1
    return count


# ── Lane CRUD ────────────────────────────────────────────────────────────────

def list_lanes(db: Session) -> list[dict[str, Any]]:
    lanes = list_entities(db, LANE_ENTITY)
    lanes.sort(key=lambda lane: lane.get("createdAt") or "")
    return lanes


def get_lane(db: Session, lane_id: str) -> dict[str, Any] | None:
    for lane in list_entities(db, LANE_ENTITY):
        if lane.get("id") == lane_id:
            return lane
    return None


def _active_lane_count(db: Session, *, excluding: str | None = None) -> int:
    return len([
        lane for lane in list_entities(db, LANE_ENTITY)
        if lane.get("enabled") and lane.get("id") != excluding
    ])


def create_lane(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    wants_enabled = bool(payload.get("enabled", True))
    if wants_enabled and _active_lane_count(db) >= MAX_ACTIVE_LANES:
        raise ValueError(f"Maximum of {MAX_ACTIVE_LANES} active lanes reached")
    lane = {
        "id": new_id("lane_"),
        "name": str(payload.get("name") or "Untitled lane").strip()[:80] or "Untitled lane",
        "filters": {**DEFAULT_LANE_FILTERS, **(payload.get("filters") or {})},
        "matchBar": max(0, min(100, int(payload.get("matchBar", 60)))),
        "dailyCap": max(1, min(100, int(payload.get("dailyCap", 5)))),
        "reviewBeforeSubmit": bool(payload.get("reviewBeforeSubmit", True)),
        "enabled": wants_enabled,
        "createdAt": now_iso(),
        "lastRunAt": None,
        "lastRunSummary": None,
    }
    return upsert_entity(db, LANE_ENTITY, lane)


def update_lane(db: Session, lane_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    current = get_lane(db, lane_id)
    if not current:
        return None
    allowed = {"name", "filters", "matchBar", "dailyCap", "reviewBeforeSubmit", "enabled"}
    clean: dict[str, Any] = {k: v for k, v in patch.items() if k in allowed and v is not None}
    if "name" in clean:
        clean["name"] = str(clean["name"]).strip()[:80] or "Untitled lane"
    if "filters" in clean:
        clean["filters"] = {**DEFAULT_LANE_FILTERS, **clean["filters"]}
    if "matchBar" in clean:
        clean["matchBar"] = max(0, min(100, int(clean["matchBar"])))
    if "dailyCap" in clean:
        clean["dailyCap"] = max(1, min(100, int(clean["dailyCap"])))
    if clean.get("enabled") and not current.get("enabled"):
        if _active_lane_count(db, excluding=lane_id) >= MAX_ACTIVE_LANES:
            raise ValueError(f"Maximum of {MAX_ACTIVE_LANES} active lanes reached")
    return patch_entity(db, LANE_ENTITY, lane_id, clean)


def delete_lane(db: Session, lane_id: str) -> bool:
    return delete_entity(db, LANE_ENTITY, lane_id)


def get_status(db: Session) -> dict[str, Any]:
    lanes = list_lanes(db)
    cap = get_shared_cap(db)
    used = _submitted_today_count(db)
    return {
        "dailyCap": cap,
        "usedToday": used,
        "remainingToday": max(0, cap - used),
        "activeLaneCount": len([lane for lane in lanes if lane.get("enabled")]),
        "lanes": lanes,
    }


def _log_run(db: Session, entry: dict[str, Any]) -> None:
    items = list(get_kv(db, RUN_LOG_KEY) or [])
    items.insert(0, {**entry, "at": _utc_now()})
    set_kv(db, RUN_LOG_KEY, items[:50])


def get_run_log(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    return list(get_kv(db, RUN_LOG_KEY) or [])[:limit]


# ── Evaluation ───────────────────────────────────────────────────────────────

async def evaluate_lanes(db: Session, *, dry_run: bool = False) -> dict[str, Any]:
    lanes = [lane for lane in list_lanes(db) if lane.get("enabled")]
    if not lanes:
        return {"success": True, "dryRun": dry_run, "queued": 0, "message": "No active lanes.", "perLane": []}

    cap = get_shared_cap(db)
    used = _submitted_today_count(db)
    budget = max(0, cap - used)
    if budget <= 0:
        result = {
            "success": True,
            "dryRun": dry_run,
            "queued": 0,
            "message": f"Shared daily cap reached ({used}/{cap}).",
            "perLane": [],
        }
        if not dry_run:
            _log_run(db, result)
        return result

    raw_jobs = list_discovered_jobs(db, active_only=True, exclude_demo=True)

    # Deep per-job LLM matches (`aa_job_match`) only exist for a small slice of
    # discovered jobs at any given time (profile-matching runs lazily/on-demand
    # elsewhere). Every discovered job DOES carry `scraperRelevancyScore` from
    # scrape time, so fall back to that for scoring/filtering rather than
    # treating "no deep match yet" as "score 0" — the latter would make lanes
    # silently starve against real data.
    matches: dict[str, dict[str, Any]] = {}
    for job in raw_jobs:
        deep_match = get_job_match(db, job["id"])
        if deep_match and deep_match.get("overallScore") is not None:
            matches[job["id"]] = {**deep_match, "_scoreSource": "deep_match"}
        else:
            matches[job["id"]] = {
                "overallScore": job.get("scraperRelevancyScore") or 0,
                "_scoreSource": "scraper_relevancy",
            }

    already_drafted_job_ids = {
        str(draft.get("jobId") or "") for draft in list_application_drafts(db) if draft.get("jobId")
    }
    pool = [job for job in raw_jobs if str(job.get("id") or "") not in already_drafted_job_ids]

    candidates: list[dict[str, Any]] = []
    seen_job_ids: set[str] = set()
    for lane in lanes:
        filters = lane.get("filters") or {}
        include_kw = [kw.strip() for kw in str(filters.get("includeKeywords", "")).split(",") if kw.strip()]
        exclude_kw = [kw.strip() for kw in str(filters.get("excludeKeywords", "")).split(",") if kw.strip()]

        lane_pool = [
            job for job in pool
            if _passes_text_filter(job.get("location", ""), filters.get("location", ""))
            and _passes_text_filter(job.get("company", ""), filters.get("company", ""))
            and _passes_freshness(job, filters.get("freshness", "all"))
        ]

        matched = filter_discovered_jobs(
            lane_pool,
            matches,
            min_match_score=lane.get("matchBar", 0),
            include_keywords=include_kw or None,
            exclude_keywords=exclude_kw or None,
        )

        lane_cap = lane.get("dailyCap", 5)
        picked = 0
        for job in matched:
            if picked >= lane_cap:
                break
            job_id = job.get("id")
            if job_id in seen_job_ids:
                continue
            seen_job_ids.add(job_id)
            score = job.get("match", {}).get("overallScore", 0)
            score_source = job.get("match", {}).get("_scoreSource", "scraper_relevancy")
            candidates.append({
                **job,
                "_score": score,
                "_scoreSource": score_source,
                "_laneId": lane["id"],
                "_laneName": lane["name"],
                "_laneReview": lane.get("reviewBeforeSubmit", True),
            })
            picked += 1

    candidates.sort(key=lambda job: job.get("_score", 0), reverse=True)
    selected = candidates[:budget]

    per_lane: dict[str, dict[str, Any]] = {
        lane["id"]: {"laneId": lane["id"], "name": lane["name"], "staged": 0, "jobs": []} for lane in lanes
    }
    staged_needing_review = 0
    staged_for_autosubmit = 0
    staged_draft_ids_for_prepare: list[str] = []

    if not dry_run:
        for job in selected:
            draft = create_application_draft(db, {
                "jobId": job["id"],
                "jobUrl": job.get("applicationUrl") or job.get("listingUrl") or "",
                "companyName": job.get("company") or "Unknown",
                "roleTitle": job.get("title") or "Unknown role",
                "provider": job.get("sourceProvider") or "auto_apply_lane",
                "matchScore": job.get("_score", 0),
            })
            update_application_draft(db, draft["id"], {
                "stagedByLaneId": job.get("_laneId"),
                "stagedByLaneName": job.get("_laneName"),
                "laneMatchScore": job.get("_score", 0),
                "laneMatchScoreSource": job.get("_scoreSource"),
            })
            review = bool(job.get("_laneReview", True))
            bucket = per_lane[job["_laneId"]]
            bucket["staged"] += 1
            bucket["jobs"].append({
                "id": job["id"],
                "draftId": draft["id"],
                "title": job.get("title"),
                "companyName": job.get("company"),
                "score": job.get("_score", 0),
                "scoreSource": job.get("_scoreSource"),
            })
            if review:
                staged_needing_review += 1
            else:
                staged_for_autosubmit += 1
                staged_draft_ids_for_prepare.append(draft["id"])

        # Commit staging now — `execute_application_prepare` below opens its
        # OWN session_scope() (its own DB connection) and must be able to see
        # the drafts we just created; the outer request-scoped session
        # otherwise wouldn't commit until this whole endpoint call returns.
        if staged_draft_ids_for_prepare or staged_needing_review:
            db.commit()

    prepare_results: list[dict[str, Any]] = []
    if not dry_run and staged_draft_ids_for_prepare:
        from app.services.application_assistant.agent import execute_application_prepare

        for draft_id in staged_draft_ids_for_prepare:
            try:
                outcome = await execute_application_prepare(draft_id, allow_retry=True)
                prepare_results.append({"draftId": draft_id, "success": bool(outcome.get("success", not outcome.get("error")))})
            except Exception as exc:  # defensive — prepare has its own internal error handling
                prepare_results.append({"draftId": draft_id, "success": False, "error": str(exc)})

    result = {
        "success": True,
        "dryRun": dry_run,
        "queued": len(selected),
        "stagedNeedingReview": staged_needing_review,
        "stagedForAutosubmit": staged_for_autosubmit,
        "budgetRemainingBefore": budget,
        "perLane": list(per_lane.values()),
        "prepareResults": prepare_results,
    }
    if not dry_run:
        _log_run(db, result)
        now = now_iso()
        for lane in lanes:
            bucket = per_lane.get(lane["id"], {})
            patch_entity(db, LANE_ENTITY, lane["id"], {"lastRunAt": now, "lastRunSummary": {"staged": bucket.get("staged", 0)}})
    return result
