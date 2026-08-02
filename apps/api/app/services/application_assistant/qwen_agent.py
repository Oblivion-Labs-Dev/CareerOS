"""Qwen autonomous application preparation and failure analysis."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.store import get_kv, now_iso, session_scope, set_kv
from app.services.application_assistant.browser_runner import prepare_application
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import (
    create_application_draft,
    create_browser_run,
    get_active_browser_run_for_app,
    get_application_draft,
    get_discovered_job,
    get_settings,
    list_answer_library,
    save_application_fields,
    update_application_draft,
    update_browser_run,
)
from app.services.application_assistant.providers import detect_provider
from app.services.application_assistant.qwen_activity import ActivityTimer, append_log
from app.services.application_assistant.worker import (
    get_app_lock,
    is_app_locked,
    is_prep_task_running,
    prep_queue_status,
    run_in_background,
    run_queued_prep,
    task_status,
    try_admit_prep,
    with_app_lock,
)

KV_AGENT_RUNS = "qwen_agent_runs"

AGENT_DEBUG_SYSTEM = """You are Qwen, the CareerOS application automation agent.
Analyze application preparation failures and explain what happened in plain language.
When the issue is a code bug, name the likely layer (UI, backend API, browser automation, extension)
and suggest a specific fix (file area, behavior change, or config).
Never suggest bypassing submission guards or auto-submitting applications.
If status is still ready_to_prepare after a failed prep attempt, that IS a failure — prep never completed.
If prepError or agentRun.error is present, cite it directly. Never say "no fix needed" when prep failed.
Be concise and actionable."""

QWEN_AGENT_SYSTEM = """You are Qwen, the autonomous application assistant inside CareerOS.
You run job application preparation in a visible browser, log every step, and help the user
understand failures. The user watches your activity log — they do not drive prep manually.
When asked what went wrong, reference the latest prep logs and diagnostics.
Suggest UI or backend fixes when automation fails due to code issues."""


def _get_agent_runs(db: Session) -> dict[str, Any]:
    return get_kv(db, KV_AGENT_RUNS) or {}


def _save_agent_run(db: Session, app_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    runs = _get_agent_runs(db)
    current = runs.get(app_id, {"applicationId": app_id})
    merged = {**current, **patch, "updatedAt": now_iso()}
    runs[app_id] = merged
    set_kv(db, KV_AGENT_RUNS, runs)
    return merged


def get_agent_run(db: Session, app_id: str) -> dict[str, Any] | None:
    return _get_agent_runs(db).get(app_id)


_STALE_AGENT_RUN_SEC = 120


def _started_age_sec(started_at: str | None) -> float:
    if not started_at:
        return _STALE_AGENT_RUN_SEC + 1
    from datetime import datetime

    try:
        t = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        return (datetime.now(UTC) - t).total_seconds()
    except (ValueError, TypeError):
        return _STALE_AGENT_RUN_SEC + 1


def reconcile_stale_prep_state(
    db: Session,
    draft: dict[str, Any],
    *,
    active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Clear orphaned in_progress / agent-run state when no prep task is actually running."""
    from app.services.application_assistant.browser_replay import (
        has_persisted_autofill_plan,
        reconcile_stale_browser_run,
    )

    app_id = str(draft.get("id") or "")
    if not app_id:
        return draft

    prep_running = task_status(f"qwen_prep_{app_id}") == "running"
    open_running = task_status(f"open_review_{app_id}") == "running"
    work_active = prep_running or open_running or is_app_locked(app_id)

    agent_run = get_agent_run(db, app_id)
    if agent_run and agent_run.get("status") == "running" and not work_active:
        if _started_age_sec(agent_run.get("startedAt")) >= _STALE_AGENT_RUN_SEC:
            _save_agent_run(
                db,
                app_id,
                {
                    "status": "failed",
                    "success": False,
                    "error": "Stale prep run cleared — no active task",
                    "completedAt": now_iso(),
                },
            )

    draft = reconcile_stale_browser_run(db, draft, active_run=active_run)

    if draft.get("status") != "in_progress" or work_active:
        return draft

    run = active_run
    if run is None:
        run = get_active_browser_run_for_app(db, app_id)
    if run and run.get("status") == "running":
        return draft

    has_saved = has_persisted_autofill_plan(draft)
    next_status = "needs_review" if has_saved else "ready_to_prepare"
    update_application_draft(db, app_id, {"status": next_status})
    return {**draft, "status": next_status}


def _log_agent(
    db: Session,
    *,
    event_type: str,
    model: str,
    success: bool,
    summary: str,
    error: str = "",
    latency_ms: int = 0,
    metadata: dict[str, Any] | None = None,
    count_as_request: bool = False,
) -> None:
    append_log(
        db,
        event_type=event_type,
        model=model,
        success=success,
        latency_ms=latency_ms,
        summary=summary,
        error=error,
        metadata=metadata or {},
        count_as_request=count_as_request,
    )


def _clear_stale_browser_runs(db: Session, app_id: str) -> None:
    """Mark orphaned browser runs stopped so blocked apps can be retried."""
    from app.services.application_assistant.persistence import ENTITY_BROWSER_RUN, list_entities

    for run in list_entities(db, ENTITY_BROWSER_RUN):
        if run.get("applicationId") == app_id and run.get("status") in ("pending", "running"):
            update_browser_run(db, run["id"], {"status": "stopped", "endedAt": now_iso()})


def _review_draft_status(result: dict[str, Any]) -> str:
    """Open-review runs should stay needs_review when the browser opened or any fields filled."""
    if result.get("success"):
        return "needs_review"
    if result.get("browserOpen") or len(result.get("filled") or []) > 0:
        return "needs_review"
    return "blocked"


def persist_prep_result(
    db: Session,
    app_id: str,
    result: dict[str, Any],
    *,
    status: str | None = None,
) -> dict[str, Any]:
    """Save field mappings, errors, skipped fields, and unrecognized fields from a prep run."""
    from app.services.application_assistant.browser_replay import ensure_replay_plan, plan_is_usable
    from app.services.application_assistant.qwen_activity import log_activity_event

    fields = result.get("fields") or []
    if fields:
        save_application_fields(db, app_id, fields)
        from app.services.application_assistant.persistence import list_answer_library, upsert_answer
        from app.services.application_assistant.semantic_field_resolution import persist_learned_variants

        persist_learned_variants(
            db,
            fields,
            upsert_answer=upsert_answer,
            list_answer_library=list_answer_library,
        )

    unknown = [f for f in fields if f.get("classification") == "unknown"]
    manual = [f for f in fields if f.get("classification") == "manual_only"]
    skipped = result.get("skipped") or []
    errors = result.get("errors") or []
    filled = result.get("filled") or []

    prep_log = {
        "timestamp": now_iso(),
        "success": bool(result.get("success")),
        "stoppedReason": result.get("stoppedReason", ""),
        "blocker": result.get("blocker"),
        "filledCount": len(filled),
        "skippedCount": len(skipped),
        "errorCount": len(errors),
        "unknownCount": len(unknown),
        "manualOnlyCount": len(manual),
        "unknownFields": [
            {
                "fieldId": f.get("fieldId") or f.get("normalizedKey"),
                "label": f.get("label"),
                "normalizedKey": f.get("normalizedKey"),
                "fieldType": f.get("fieldType"),
                "required": f.get("required"),
                "section": f.get("section"),
                "selectorHint": f.get("selectorHint"),
                "options": f.get("options") or [],
                "sensitivityCategory": f.get("sensitivityCategory", "none"),
            }
            for f in unknown[:60]
        ],
        "skipped": skipped[:40],
        "errors": errors[:20],
        "tracePath": result.get("tracePath", ""),
    }

    draft_status = status or ("needs_review" if result.get("success") else "blocked")
    patch: dict[str, Any] = {
        "status": draft_status,
        "screenshots": result.get("screenshots", []),
        "errors": errors,
        "skipped": skipped,
        "prepLog": prep_log,
        "stoppedReason": result.get("stoppedReason", ""),
        "currentPage": result.get("state", {}).get("progress", {}).get("currentUrl", ""),
        "currentSection": result.get("state", {}).get("progress", {}).get("currentSection", ""),
    }
    browser_plan = result.get("browserPlan")
    draft = get_application_draft(db, app_id) or {}
    rebuilt = ensure_replay_plan(
        browser_plan,
        fields,
        nav_url=str(draft.get("jobUrl") or ""),
        source_url=str(draft.get("jobUrl") or ""),
        provider=str(draft.get("provider") or ""),
    )
    if plan_is_usable(rebuilt):
        patch["browserPlan"] = rebuilt
    update_application_draft(
        db,
        app_id,
        patch,
    )

    unknown_labels = ", ".join(f.get("label", "?") for f in unknown[:8])
    if len(unknown) > 8:
        unknown_labels += f" (+{len(unknown) - 8} more)"
    log_activity_event(
        event_type="prep_field_report",
        summary=(
            f"Filled {len(filled)}, unrecognized {len(unknown)}, skipped {len(skipped)}, "
            f"errors {len(errors)}. {unknown_labels or 'No unknown fields'}"
        )[:300],
        success=bool(result.get("success")),
        error=errors[0].get("error", "") if errors and isinstance(errors[0], dict) else "",
        metadata={
            "applicationId": app_id,
            "filledCount": len(filled),
            "unknownCount": len(unknown),
            "skippedCount": len(skipped),
            "errorCount": len(errors),
            "stoppedReason": result.get("stoppedReason", ""),
        },
    )

    return prep_log


async def execute_application_prepare(app_id: str, *, allow_retry: bool = False) -> dict[str, Any]:
    """Run Playwright prep for an application draft. Shared by direct and agent routes."""
    from app.db.store import session_scope

    lock = get_app_lock(app_id)
    if lock.locked():
        return {"success": False, "error": "Application is already being prepared"}

    async with lock:
        with session_scope() as db:
            draft = get_application_draft(db, app_id)
            if not draft:
                return {"success": False, "error": "Application not found"}

            active_run = get_active_browser_run_for_app(db, app_id)
            if active_run:
                from app.services.application_assistant.browser_runner import get_active_session

                prep_running = task_status(f"qwen_prep_{app_id}") == "running"
                open_running = task_status(f"open_review_{app_id}") == "running"
                if not prep_running and not open_running and not get_active_session(app_id):
                    _clear_stale_browser_runs(db, app_id)
                    active_run = get_active_browser_run_for_app(db, app_id)
                elif (
                    allow_retry
                    and draft.get("status") in ("blocked", "ready_to_prepare", "needs_review")
                    and not prep_running
                    and not open_running
                    and not get_active_session(app_id)
                ):
                    _clear_stale_browser_runs(db, app_id)
                    active_run = None
            if active_run:
                return {"success": False, "error": "Browser run already active"}

            settings = get_settings(db)
            provider_name, adapter, supported = detect_provider(draft.get("jobUrl", ""))
            if not supported or not adapter:
                return {"success": False, "error": f"Provider '{provider_name}' is not supported"}

            profile = get_kv(db, "profile") or {}
            answer_library = list_answer_library(db)
            documents = get_kv(db, "documents") or {}
            browser_run = create_browser_run(db, {"applicationId": app_id, "status": "running"})
            update_application_draft(db, app_id, {"status": "in_progress", "browserRunId": browser_run["id"]})

            browser_run_id = browser_run["id"]
            job_url = draft.get("jobUrl", "")
            context = {
                "profile": profile,
                "answerLibrary": answer_library,
                "allowInferred": settings.get("allowInferredAnswers", False),
                "documents": documents,
                "assistantSettings": settings,
                "companyName": draft.get("companyName", ""),
            }
            headed = settings.get("browser", {}).get("headed", True)

        try:
            result = await prepare_application(
                application_url=job_url,
                adapter=adapter,
                context=context,
                app_id=app_id,
                headed=headed,
            )
        except Exception as exc:
            error_text = str(exc) or repr(exc)
            result = {
                "success": False,
                "fields": [],
                "filled": [],
                "skipped": [],
                "screenshots": [],
                "errors": [{"error": error_text, "type": type(exc).__name__}],
                "stoppedReason": f"Error: {error_text}",
            }

        with session_scope() as db:
            persist_prep_result(db, app_id, result)

            from app.services.application_assistant.field_answers import (
                finalize_post_prep_field_analysis,
                sync_application_readiness_async,
            )

            readiness = await sync_application_readiness_async(db, app_id, persist=True)
            company = str((get_application_draft(db, app_id) or {}).get("companyName") or "")
            await finalize_post_prep_field_analysis(
                db,
                app_id,
                readiness,
                analyze_context={"applicationId": app_id, "companyName": company},
            )
            if not readiness.get("readyForBrowser"):
                from app.services.application_assistant.qwen_activity import log_activity_event

                log_activity_event(
                    event_type="profile_questions_required",
                    summary=f"{readiness.get('pendingCount', 0)} profile questions must be answered before opening browser",
                    metadata={"applicationId": app_id, "pendingCount": readiness.get("pendingCount", 0)},
                )

            update_browser_run(
                db,
                browser_run_id,
                {
                    "status": "completed" if result.get("success") else "failed",
                    "endedAt": now_iso(),
                    "tracePath": result.get("tracePath", ""),
                },
            )

            return {
                "success": result.get("success", False),
                "result": result,
                "application": get_application_draft(db, app_id),
            }


async def _run_open_review_prepare(db: Session, app_id: str, browser_run_id: str) -> dict[str, Any]:
    """Launch browser and fill the employer form from saved draft data."""
    from app.services.application_assistant.qwen_activity import log_activity_event

    draft = get_application_draft(db, app_id)
    if not draft:
        return {"success": False, "error": "Application not found"}

    settings = get_settings(db)
    provider_name, adapter, supported = detect_provider(draft.get("jobUrl", ""))
    if not supported or not adapter:
        update_browser_run(
            db,
            browser_run_id,
            {"status": "failed", "endedAt": now_iso(), "error": f"Unsupported provider: {provider_name}"},
        )
        update_application_draft(db, app_id, {"status": "needs_review"})
        return {"success": False, "error": f"Provider '{provider_name}' is not supported"}

    profile = get_kv(db, "profile") or {}
    answer_library = list_answer_library(db)
    documents = get_kv(db, "documents") or {}
    context = {
        "profile": profile,
        "answerLibrary": answer_library,
        "allowInferred": settings.get("allowInferredAnswers", False),
        "reviewMode": True,
        "savedFields": draft.get("fields") or [],
        "browserPlan": draft.get("browserPlan"),
        "documents": documents,
        "assistantSettings": settings,
        "companyName": draft.get("companyName", ""),
    }
    headed = settings.get("browser", {}).get("headed", True)

    # Persist the running state before the Playwright worker emits activity
    # through its own session; SQLite permits only one writer at a time.
    db.commit()

    result = await prepare_application(
        application_url=draft.get("jobUrl", ""),
        adapter=adapter,
        context=context,
        app_id=app_id,
        headed=headed,
    )

    persist_prep_result(db, app_id, result, status=_review_draft_status(result))

    update_browser_run(
        db,
        browser_run_id,
        {
            "status": "completed" if result.get("success") else "failed",
            "endedAt": now_iso(),
            "tracePath": result.get("tracePath", ""),
            "error": result.get("error") or result.get("stoppedReason") or "",
        },
    )

    app = get_application_draft(db, app_id)
    if result.get("success") and result.get("browserOpen"):
        message = "Application form opened with your saved data — review remaining fields and submit manually"
        review_status = "browser_open"
    elif result.get("success"):
        message = "Application data refreshed"
        review_status = "ready"
    else:
        message = result.get("stoppedReason") or result.get("error") or "Could not open application form"
        review_status = "failed"

    log_activity_event(
        event_type="review_open_complete" if result.get("success") else "review_open_failed",
        summary=message[:300],
        success=bool(result.get("success")),
        error="" if result.get("success") else message[:200],
        metadata={
            "applicationId": app_id,
            "status": review_status,
            "browserOpen": bool(result.get("browserOpen")),
            "verifiedCount": app.get("verifiedCount", 0) if app else 0,
            "missingCount": app.get("missingCount", 0) if app else 0,
        },
        db=db,
    )

    return {
        "success": result.get("success", False),
        "browserOpen": bool(result.get("browserOpen")),
        "status": review_status,
        "message": message,
        "jobUrl": draft.get("jobUrl", ""),
        "application": app,
        "result": result,
    }


async def _open_review_background(app_id: str, browser_run_id: str) -> None:
    async def work(db: Session) -> None:
        await _run_open_review_prepare(db, app_id, browser_run_id)

    await with_app_lock(app_id, work)


async def execute_application_open_review(
    db: Session,
    app_id: str,
    *,
    force_reopen: bool = False,
    background: bool = False,
    allow_parallel: bool = True,
) -> dict[str, Any]:
    """Open the employer application form in a visible browser and fill from saved draft."""
    _ = allow_parallel  # kept for API compat; browsers use per-app profiles and no longer close each other
    from app.services.application_assistant.browser_runner import (
        close_session,
        focus_session,
        get_active_session,
    )
    from app.services.application_assistant.field_answers import (
        sync_application_readiness,
        sync_application_readiness_async,
    )
    from app.services.application_assistant.qwen_activity import log_activity_event

    draft = get_application_draft(db, app_id)
    if not draft:
        return {"success": False, "error": "Application not found"}

    if not force_reopen and get_active_session(app_id):
        await focus_session(app_id)
        return {
            "success": True,
            "browserOpen": True,
            "alreadyOpen": True,
            "status": "browser_open",
            "message": "Application form is already open — brought Chrome to the front.",
            "application": draft,
            "jobUrl": draft.get("jobUrl", ""),
        }

    if force_reopen:
        await close_session(app_id)
        _clear_stale_browser_runs(db, app_id)

    open_task_id = f"open_review_{app_id}"
    if is_prep_task_running(app_id):
        return {
            "success": False,
            "error": "Qwen is still preparing this application — wait for prep to finish, then use the browser window it opened.",
            "status": "preparing",
        }
    if is_app_locked(app_id):
        return {
            "success": False,
            "error": "Application is busy (prep or review in progress) — wait a moment and try again.",
            "status": "busy",
        }
    if task_status(open_task_id) == "running":
        return {
            "success": False,
            "error": "Already opening this application in the browser",
            "status": "opening",
        }

    if draft.get("readyForBrowser") and int(draft.get("pendingFieldCount") or 0) == 0:
        readiness = {"readyForBrowser": True, "pendingCount": 0}
    elif draft.get("aiAnalyzed"):
        readiness = sync_application_readiness(db, app_id, persist=True)
    else:
        readiness = await sync_application_readiness_async(db, app_id, persist=True)
    if not readiness.get("readyForBrowser"):
        pending_count = readiness.get("pendingCount", 0)
        return {
            "success": False,
            "error": f"Answer {pending_count} profile question(s) before opening the browser",
            "status": "profile_incomplete",
            "pendingFieldCount": pending_count,
            "readyForBrowser": False,
        }

    log_activity_event(
        event_type="review_open_start",
        summary=f"Opening review form: {draft.get('companyName')} — {draft.get('roleTitle')}",
        metadata={"applicationId": app_id, "jobUrl": draft.get("jobUrl", "")},
        db=db,
    )

    _clear_stale_browser_runs(db, app_id)

    provider_name, adapter, supported = detect_provider(draft.get("jobUrl", ""))
    if not supported or not adapter:
        return {"success": False, "error": f"Provider '{provider_name}' is not supported"}

    browser_run = create_browser_run(db, {"applicationId": app_id, "status": "running"})
    update_application_draft(db, app_id, {"status": "in_progress", "browserRunId": browser_run["id"]})

    if background:
        await run_in_background(open_task_id, _open_review_background(app_id, browser_run["id"]))
        return {
            "success": True,
            "browserOpen": False,
            "status": "opening",
            "message": "Launching browser and filling saved fields…",
            "application": get_application_draft(db, app_id),
            "jobUrl": draft.get("jobUrl", ""),
        }

    return await _run_open_review_prepare(db, app_id, browser_run["id"])


def get_review_session_status(db: Session, app_id: str) -> dict[str, Any]:
    """Report whether open-review is idle, in progress, browser open, or failed."""
    from datetime import datetime

    from app.services.application_assistant.browser_replay import quick_apply_info, reconcile_stale_browser_run
    from app.services.application_assistant.browser_runner import get_active_session

    draft = get_application_draft(db, app_id)
    if not draft:
        return {"status": "not_found", "browserOpen": False, "message": "Application not found"}

    draft = reconcile_stale_browser_run(db, draft)
    draft = get_application_draft(db, app_id) or draft

    def with_quick_apply(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **payload,
            **quick_apply_info(draft, browser_open=bool(payload.get("browserOpen"))),
        }

    if draft.get("status") == "submitted_manually":
        browser_open = bool(get_active_session(app_id))
        source = str(draft.get("submissionSource") or "manual")
        auto = source == "auto"
        return with_quick_apply({
            "status": "submitted",
            "browserOpen": browser_open,
            "submitted": True,
            "submittedAt": draft.get("submittedAt"),
            "submissionSource": source,
            "message": (
                "Application submitted on the job site — marked automatically in CareerOS."
                if auto
                else "Application marked submitted."
            ),
            "verifiedCount": draft.get("verifiedCount", 0),
            "missingCount": draft.get("missingCount", 0),
            "progress": draft.get("progress", 0),
            "jobUrl": draft.get("jobUrl", ""),
        })

    if get_active_session(app_id):
        return with_quick_apply({
            "status": "browser_open",
            "browserOpen": True,
            "message": "Form is open in your browser — submit on the job site and CareerOS will mark it submitted automatically.",
            "verifiedCount": draft.get("verifiedCount", 0),
            "missingCount": draft.get("missingCount", 0),
            "progress": draft.get("progress", 0),
            "jobUrl": draft.get("jobUrl", ""),
        })

    active_run = get_active_browser_run_for_app(db, app_id)
    if draft.get("status") == "in_progress" and active_run:
        run_status = str(active_run.get("status") or "")
        if run_status == "failed":
            err = str(active_run.get("error") or "").strip()
            update_application_draft(db, app_id, {"status": "needs_review"})
            return with_quick_apply({
                "status": "failed",
                "browserOpen": False,
                "message": err or "Could not open the application form — try Click to complete again.",
                "jobUrl": draft.get("jobUrl", ""),
            })

        open_running = task_status(f"open_review_{app_id}") == "running"
        live_session = bool(get_active_session(app_id))
        if open_running or live_session:
            started_at = active_run.get("startedAt", "")
            try:
                t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                age_sec = (datetime.now(UTC) - t).total_seconds()
                return with_quick_apply({
                    "status": "opening",
                    "browserOpen": live_session,
                    "message": f"Opening form and filling saved data… ({int(age_sec)}s)",
                    "elapsedSec": int(age_sec),
                    "jobUrl": draft.get("jobUrl", ""),
                })
            except (ValueError, TypeError):
                pass

        update_application_draft(db, app_id, {"status": "needs_review"})
        draft = get_application_draft(db, app_id) or draft

    if draft.get("status") == "needs_review":
        ready = draft.get("readyForBrowser")
        pending_count = draft.get("pendingFieldCount", draft.get("missingCount", 0))
        if ready is False or (pending_count and pending_count > 0):
            return with_quick_apply({
                "status": "profile_incomplete",
                "browserOpen": False,
                "readyForBrowser": False,
                "pendingFieldCount": pending_count,
                "message": f"Answer {pending_count} profile question(s) below before opening the browser.",
                "verifiedCount": draft.get("verifiedCount", 0),
                "missingCount": draft.get("missingCount", 0),
                "progress": draft.get("progress", 0),
                "jobUrl": draft.get("jobUrl", ""),
            })
        return with_quick_apply({
            "status": "ready",
            "browserOpen": False,
            "readyForBrowser": True,
            "pendingFieldCount": 0,
            "message": "Ready — click Open in browser to launch the application form.",
            "verifiedCount": draft.get("verifiedCount", 0),
            "missingCount": draft.get("missingCount", 0),
            "progress": draft.get("progress", 0),
            "jobUrl": draft.get("jobUrl", ""),
        })

    if draft.get("status") == "blocked":
        errors = draft.get("errors") or []
        err_msg = errors[0].get("error", "") if errors and isinstance(errors[0], dict) else ""
        if draft.get("readyForBrowser") and int(draft.get("pendingFieldCount") or 0) == 0:
            return with_quick_apply({
                "status": "ready",
                "browserOpen": False,
                "readyForBrowser": True,
                "pendingFieldCount": 0,
                "message": "Ready — click Open in browser to launch the application form.",
                "verifiedCount": draft.get("verifiedCount", 0),
                "missingCount": draft.get("missingCount", 0),
                "progress": draft.get("progress", 0),
                "jobUrl": draft.get("jobUrl", ""),
            })
        return with_quick_apply({
            "status": "failed",
            "browserOpen": False,
            "message": err_msg or "Application is blocked — try Ask Qwen to resume.",
            "jobUrl": draft.get("jobUrl", ""),
        })

    return with_quick_apply({
        "status": "idle",
        "browserOpen": False,
        "message": "",
        "jobUrl": draft.get("jobUrl", ""),
    })


def _build_diagnostics_bundle(db: Session, app_id: str, prep_result: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.services.application_assistant.qwen_activity import get_logs

    draft = get_application_draft(db, app_id) or {}
    prep = prep_result or {}
    result = prep.get("result") or {}
    agent_run = get_agent_run(db, app_id) or {}
    recent_logs = [
        {
            "type": log.get("type"),
            "summary": log.get("summary"),
            "success": log.get("success"),
            "error": log.get("error"),
        }
        for log in get_logs(db, limit=20)
        if (log.get("metadata") or {}).get("applicationId") == app_id
    ]
    return {
        "applicationId": app_id,
        "company": draft.get("companyName"),
        "role": draft.get("roleTitle"),
        "provider": draft.get("provider"),
        "status": draft.get("status"),
        "jobUrl": draft.get("jobUrl"),
        "prepSuccess": prep.get("success"),
        "prepError": prep.get("error") or agent_run.get("error"),
        "stoppedReason": result.get("stoppedReason") or draft.get("stoppedReason"),
        "blocker": result.get("blocker"),
        "errors": draft.get("errors") or result.get("errors"),
        "agentRun": {
            "status": agent_run.get("status"),
            "success": agent_run.get("success"),
            "error": agent_run.get("error"),
            "stoppedReason": agent_run.get("stoppedReason"),
        },
        "fieldCounts": {
            "verified": draft.get("verifiedCount", 0),
            "review": draft.get("reviewCount", 0),
            "missing": draft.get("missingCount", 0),
            "conflicting": draft.get("conflictingCount", 0),
        },
        "screenshots": draft.get("screenshots") or result.get("screenshots"),
        "recentPrepLogs": recent_logs[:12],
    }


def _rule_based_prep_failure_summary(bundle: dict[str, Any], prep_result: dict[str, Any]) -> str | None:
    prep_error = str(prep_result.get("error") or bundle.get("prepError") or "").strip()
    stopped = str(bundle.get("stoppedReason") or "").strip()
    status = str(bundle.get("status") or "")
    agent = bundle.get("agentRun") or {}

    combined = f"{prep_error} {stopped}".lower()
    if "timeout" in combined:
        return (
            "Prep timed out while Playwright or Qwen was still working. "
            "Keep Ollama/Qwen running, then click Start preparation again. "
            "Large forms can take several minutes."
        )
    if prep_error:
        return f"Prep failed: {prep_error}. Click Start preparation to retry."
    if status == "ready_to_prepare" and not prep_result.get("success"):
        return (
            "Prep did not finish — the application is still ready_to_prepare with no fields mapped. "
            "Click Start preparation again and watch the Qwen live panel for browser + mapping steps."
        )
    if stopped:
        return f"Prep stopped: {stopped}"
    if agent.get("status") == "failed" and agent.get("error"):
        return f"Last prep run failed: {agent['error']}"
    return None


async def analyze_prep_failure(db: Session, app_id: str, prep_result: dict[str, Any]) -> str:
    """Explain prep failure with deterministic summary first, then optional LLM detail."""
    bundle = _build_diagnostics_bundle(db, app_id, prep_result)
    rule_summary = _rule_based_prep_failure_summary(bundle, prep_result)
    if rule_summary:
        return rule_summary

    settings = get_settings(db)
    client = create_llm_client(settings)
    if not client.enabled:
        return rule_summary or "LLM not configured — cannot analyze failure."

    prompt = (
        "Application preparation did not complete successfully. Analyze this diagnostics bundle "
        "and explain:\n"
        "1. What happened (user-friendly)\n"
        "2. Root cause category: user_data | site_blocker | automation | ui | backend\n"
        "3. If ui or backend: specific fix suggestion (component, route, or adapter change)\n\n"
        "Important: if status is ready_to_prepare after a failed attempt, prep never completed.\n"
        f"Rule-based summary (may help): {rule_summary or 'none'}\n\n"
        f"Diagnostics:\n{json.dumps(bundle, indent=2)[:4000]}"
    )

    with ActivityTimer() as timer:
        analysis = await client.complete(prompt, system=AGENT_DEBUG_SYSTEM)

    summary = str(analysis.get("data", ""))[:500] if analysis.get("success") else analysis.get("error", "Analysis failed")
    _log_agent(
        db,
        event_type="agent_analysis",
        model=client.model,
        success=analysis.get("success", False),
        latency_ms=timer.elapsed_ms,
        summary=summary[:300],
        error=analysis.get("error", ""),
        metadata={"applicationId": app_id, "category": "prep_failure"},
        count_as_request=True,
    )
    return summary if analysis.get("success") else f"Analysis failed: {analysis.get('error', 'unknown')}"


async def _autonomous_prepare_app(app_id: str) -> None:
    """Background task: prep application, log steps, analyze on failure."""
    with session_scope() as db:
        settings = get_settings(db)
        client = create_llm_client(settings)
        model = client.model or "qwen"
        draft = get_application_draft(db, app_id)
        if not draft:
            _save_agent_run(db, app_id, {"status": "failed", "error": "Application not found"})
            return

        _save_agent_run(
            db,
            app_id,
            {
                "status": "running",
                "companyName": draft.get("companyName"),
                "roleTitle": draft.get("roleTitle"),
                "startedAt": now_iso(),
                "error": "",
                "analysis": "",
            },
        )
        _log_agent(
            db,
            event_type="agent_prep_start",
            model=model,
            success=True,
            summary=f"Qwen starting prep: {draft.get('companyName')} — {draft.get('roleTitle')}",
            metadata={"applicationId": app_id, "jobUrl": draft.get("jobUrl", "")},
        )

    prep_result: dict[str, Any] = {"success": False}
    try:
        prep_result = await execute_application_prepare(app_id, allow_retry=True)
    except Exception as exc:
        prep_result = {"success": False, "error": str(exc)}

    with session_scope() as db:
        settings = get_settings(db)
        client = create_llm_client(settings)
        model = client.model or "qwen"
        success = prep_result.get("success", False)
        app = prep_result.get("application") or get_application_draft(db, app_id) or {}
        stopped = (prep_result.get("result") or {}).get("stoppedReason", "")

        _log_agent(
            db,
            event_type="agent_prep_complete" if success else "agent_prep_failed",
            model=model,
            success=success,
            summary=(
                f"Prep {'completed' if success else 'failed'}: "
                f"{app.get('verifiedCount', 0)} verified, {app.get('missingCount', 0)} missing. {stopped}"
            )[:300],
            error="" if success else stopped or prep_result.get("error", "Unknown error"),
            metadata={
                "applicationId": app_id,
                "status": app.get("status"),
                "verifiedCount": app.get("verifiedCount", 0),
                "missingCount": app.get("missingCount", 0),
            },
        )

        analysis = ""
        if not success or app.get("status") == "blocked":
            analysis = await analyze_prep_failure(db, app_id, prep_result)

        _save_agent_run(
            db,
            app_id,
            {
                "status": "completed" if success else "failed",
                "completedAt": now_iso(),
                "success": success,
                "applicationStatus": app.get("status"),
                "verifiedCount": app.get("verifiedCount", 0),
                "missingCount": app.get("missingCount", 0),
                "stoppedReason": stopped or prep_result.get("error", ""),
                "error": "" if success else (prep_result.get("error") or stopped or "Prep failed"),
                "analysis": analysis,
            },
        )


async def start_autonomous_prepare_for_job(job_id: str) -> dict[str, Any]:
    """Create application draft (if needed) and start Qwen prep in background."""
    with session_scope() as db:
        job = get_discovered_job(db, job_id)
        if not job:
            return {"success": False, "error": "Job not found"}

        from app.services.application_assistant.persistence import get_job_match

        match = get_job_match(db, job_id)
        draft = create_application_draft(
            db,
            {
                "jobId": job_id,
                "jobUrl": job.get("applicationUrl", job.get("listingUrl", "")),
                "companyName": job.get("company", ""),
                "roleTitle": job.get("title", ""),
                "provider": job.get("sourceProvider", "unknown"),
                "matchScore": match.get("overallScore", 0) if match else 0,
            },
        )
        app_id = draft["id"]

    await start_autonomous_prepare(app_id)
    return {"success": True, "applicationId": app_id, "application": draft}


async def start_autonomous_prepare(app_id: str) -> dict[str, Any]:
    """Kick off background Qwen prep for an existing application."""
    try:
        with session_scope() as db:
            draft = get_application_draft(db, app_id)
            if not draft:
                return {"success": False, "error": "Application not found"}
            run = get_agent_run(db, app_id)
            prep_task_state = task_status(f"qwen_prep_{app_id}")
            if run and run.get("status") == "running":
                if prep_task_state == "running" or is_app_locked(app_id):
                    return {
                        "success": True,
                        "applicationId": app_id,
                        "status": "running",
                        "queue": prep_queue_status(),
                    }
                _save_agent_run(db, app_id, {"status": "failed", "error": "Stale run cleared for retry"})
            if draft.get("status") in ("blocked", "ready_to_prepare", "needs_review", "in_progress"):
                _clear_stale_browser_runs(db, app_id)
    except OperationalError as exc:
        return {
            "success": False,
            "applicationId": app_id,
            "error": f"Database busy — could not start prep: {exc}",
            "queue": prep_queue_status(),
        }

    admitted = await try_admit_prep(app_id)
    if not admitted:
        queue = prep_queue_status()
        return {
            "success": False,
            "error": f"Prep queue full ({queue['queued']}/{queue['maxQueue']}). Wait for running jobs to finish.",
            "queue": queue,
        }

    async def _start() -> None:
        await run_queued_prep(app_id, _autonomous_prepare_app(app_id))

    await run_in_background(f"qwen_prep_{app_id}", _start())
    return {"success": True, "applicationId": app_id, "status": "running", "queue": prep_queue_status()}


def schedule_autonomous_prepare(app_id: str) -> None:
    """Fire-and-forget prep kickoff — safe to call from save endpoints."""
    async def _kickoff() -> None:
        try:
            await start_autonomous_prepare(app_id)
        except Exception as exc:
            from app.services.application_assistant.qwen_activity import log_activity_event

            log_activity_event(
                event_type="agent_error",
                summary=f"Could not schedule prep after save: {exc}",
                success=False,
                error=str(exc),
                metadata={"applicationId": app_id},
            )

    try:
        asyncio.get_running_loop().create_task(_kickoff())
    except RuntimeError:
        pass


def build_chat_context(db: Session, context: dict[str, Any]) -> str:
    """Enrich Qwen chat with latest agent run and diagnostics."""
    parts: list[str] = []
    app_id = context.get("applicationId") or context.get("application_id")
    if app_id:
        run = get_agent_run(db, str(app_id))
        draft = get_application_draft(db, str(app_id))
        if run:
            parts.append(f"Latest Qwen agent run for {app_id}: {json.dumps(run)[:1500]}")
        if draft:
            parts.append(
                f"Application state: status={draft.get('status')}, "
                f"verified={draft.get('verifiedCount')}, missing={draft.get('missingCount')}, "
                f"errors={draft.get('errors')}"
            )
        if run and run.get("analysis"):
            parts.append(f"Qwen prior analysis: {run['analysis'][:800]}")

    if context.get("applicationsCount") is not None:
        parts.append(
            f"Tracker: {context['applicationsCount']} applications, "
            f"{context.get('submittedCount', 0)} submitted."
        )
    return "\n".join(parts)
