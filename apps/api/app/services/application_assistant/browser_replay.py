"""Saved Playwright replay plans for instant open-review after prep."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.store import now_iso
from app.services.application_assistant.answer_classification import should_skip_autofill_field
from app.services.application_assistant.css_selectors import normalize_css_selector

PLAN_VERSION = 1

_ACTION_KEYS = (
    "type",
    "selector",
    "selectorHint",
    "value",
    "fieldId",
    "fieldLabel",
    "normalizedKey",
    "fieldType",
    "section",
    "valueRef",
    "filePath",
)

_STALE_BROWSER_RUN_SEC = 300
_STALE_BROWSER_RUN_IDLE_SEC = 45


def serialize_fill_action(action: dict[str, Any]) -> dict[str, Any]:
    return {key: action[key] for key in _ACTION_KEYS if key in action and action[key] is not None}


def build_browser_plan(
    *,
    nav_url: str,
    source_url: str,
    provider: str,
    fill_actions: list[dict[str, Any]],
    use_iframe: bool = False,
    iframe_selector: str = "",
    form_nav_url: str = "",
) -> dict[str, Any]:
    """Capture the minimal steps Playwright needs to reopen and autofill quickly."""
    plan: dict[str, Any] = {
        "version": PLAN_VERSION,
        "navUrl": nav_url,
        "sourceUrl": source_url,
        "provider": provider,
        "useIframe": use_iframe,
        "iframeSelector": iframe_selector or "iframe[src*='greenhouse.io']",
        "fillActions": [serialize_fill_action(action) for action in fill_actions],
        "actionCount": len(fill_actions),
        "savedAt": now_iso(),
    }
    if form_nav_url:
        plan["formNavUrl"] = form_nav_url
    return plan


def hydrate_fill_actions(
    plan_actions: list[dict[str, Any]],
    saved_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge latest proposed values from the draft onto saved fill actions."""
    from app.services.application_assistant.field_fill_engine import effective_replay_field_type

    by_id = {
        str(field.get("fieldId")): field
        for field in saved_fields
        if field.get("fieldId")
    }
    by_key = {
        str(field.get("normalizedKey")): field
        for field in saved_fields
        if field.get("normalizedKey")
    }

    hydrated: list[dict[str, Any]] = []
    for action in plan_actions:
        merged = dict(action)
        field = by_id.get(str(action.get("fieldId") or "")) or by_key.get(str(action.get("normalizedKey") or ""))
        if field is not None:
            if field.get("proposedValue") is not None:
                merged["value"] = field.get("proposedValue")
                if (
                    str(merged.get("type") or "") == "upload_document"
                    or str(field.get("fieldType") or "").lower() == "file"
                ):
                    merged["filePath"] = field.get("proposedValue")
            if field.get("selectorHint"):
                merged["selector"] = field.get("selectorHint")
                merged["selectorHint"] = field.get("selectorHint")
        merged["fieldType"] = effective_replay_field_type(merged)
        hydrated.append(merged)
    return hydrated


def normalize_replay_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply replay-safe field types so saved steps fill correctly on quick apply."""
    from app.services.application_assistant.field_fill_engine import effective_replay_field_type

    normalized: list[dict[str, Any]] = []
    for action in actions:
        merged = dict(action)
        merged["fieldType"] = effective_replay_field_type(merged)
        normalized.append(merged)
    return normalized


def merge_plan_actions_with_fields(
    plan_actions: list[dict[str, Any]],
    saved_fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Hydrate persisted plan steps and append any replayable saved fields missing from the plan."""
    hydrated = hydrate_fill_actions(plan_actions, saved_fields)
    seen_ids = {str(action.get("fieldId") or "") for action in hydrated if action.get("fieldId")}
    seen_keys = {str(action.get("normalizedKey") or "") for action in hydrated if action.get("normalizedKey")}

    for built in build_replay_actions_from_fields(saved_fields):
        field_id = str(built.get("fieldId") or "")
        normalized_key = str(built.get("normalizedKey") or "")
        if field_id and field_id in seen_ids:
            continue
        if normalized_key and normalized_key in seen_keys:
            continue
        hydrated.append(built)
        if field_id:
            seen_ids.add(field_id)
        if normalized_key:
            seen_keys.add(normalized_key)

    return normalize_replay_actions(hydrated)


def ensure_document_upload_actions(
    actions: list[dict[str, Any]],
    saved_fields: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Ensure resume/cover uploads are present with fresh materialized file paths."""
    from pathlib import Path

    from app.services.application_assistant.document_files import apply_document_fields

    merged_actions = [dict(action) for action in actions]
    prepared_fields = apply_document_fields([dict(field) for field in saved_fields], context)

    def _matches_upload(action: dict[str, Any], field: dict[str, Any], selector: str) -> bool:
        if str(action.get("type") or "") != "upload_document":
            return False
        field_id = str(field.get("fieldId") or "")
        if field_id and str(action.get("fieldId") or "") == field_id:
            return True
        action_selector = normalize_css_selector(str(action.get("selector") or action.get("selectorHint") or ""))
        return bool(selector and action_selector == selector)

    for field in prepared_fields:
        if str(field.get("fieldType") or "").lower() != "file":
            continue
        file_path = str(field.get("proposedValue") or "").strip()
        if not file_path or not Path(file_path).is_file():
            continue
        selector = normalize_css_selector(str(field.get("selectorHint") or ""))
        if not selector:
            continue

        updated = False
        for action in merged_actions:
            if _matches_upload(action, field, selector):
                action["filePath"] = file_path
                action["fileName"] = str(field.get("documentFileName") or Path(file_path).name)
                action["selector"] = selector
                action["selectorHint"] = field.get("selectorHint") or selector
                action["fieldType"] = "file"
                updated = True
                break

        if updated:
            continue

        merged_actions.append(
            {
                "type": "upload_document",
                "selector": selector,
                "selectorHint": field.get("selectorHint") or selector,
                "filePath": file_path,
                "fileName": str(field.get("documentFileName") or Path(file_path).name),
                "fieldId": field.get("fieldId"),
                "fieldLabel": field.get("label"),
                "normalizedKey": field.get("normalizedKey"),
                "fieldType": "file",
                "section": field.get("section"),
                "valueRef": field.get("valueRef"),
            }
        )

    return merged_actions


def resolve_review_replay_plan(
    draft_plan: dict[str, Any] | None,
    saved_fields: list[dict[str, Any]],
    *,
    nav_url: str,
    source_url: str = "",
    provider: str = "",
    use_iframe: bool = False,
    iframe_selector: str = "",
) -> dict[str, Any] | None:
    """Resolve a replay plan for quick apply / open-review from saved prep state."""
    return ensure_replay_plan(
        draft_plan,
        saved_fields,
        nav_url=nav_url,
        source_url=source_url,
        provider=provider,
        use_iframe=use_iframe,
        iframe_selector=iframe_selector,
    )


def plan_is_usable(plan: dict[str, Any] | None) -> bool:
    return bool(
        plan
        and plan.get("version") == PLAN_VERSION
        and plan.get("navUrl")
        and len(plan.get("fillActions") or []) > 0
    )


def effective_autofill_step_count(draft: dict[str, Any]) -> int:
    """Count replayable steps from the saved plan or rebuildable field mappings."""
    stored_plan = draft.get("browserPlan") or {}
    count = int(stored_plan.get("actionCount") or len(stored_plan.get("fillActions") or []) or 0)
    if count > 0:
        return count
    return len(build_replay_actions_from_fields(draft.get("fields") or []))


def has_persisted_autofill_plan(draft: dict[str, Any]) -> bool:
    """True when prep saved at least one replayable autofill step."""
    return effective_autofill_step_count(draft) > 0


def _replayable_field(field: dict[str, Any]) -> bool:
    if should_skip_autofill_field(field):
        return False
    if field.get("classification") == "manual_only":
        return False
    if field.get("filled"):
        return True
    if field.get("classification") in {"verified", "inferred"}:
        return True
    if (
        field.get("selectorHint")
        and field.get("proposedValue") not in (None, "")
        and field.get("classification") not in {"unknown", "manual_only"}
    ):
        return True
    return False


def build_replay_actions_from_fields(saved_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild fill actions from persisted draft fields when the saved plan is empty."""
    actions: list[dict[str, Any]] = []
    for field in saved_fields:
        if not _replayable_field(field):
            continue
        selector = normalize_css_selector(str(field.get("selectorHint") or ""))
        if not selector:
            continue
        field_type = str(field.get("fieldType") or "text").lower()
        value = field.get("proposedValue")
        if field_type == "file":
            from pathlib import Path

            if not value or not Path(str(value)).is_file():
                continue
            actions.append(
                {
                    "type": "upload_document",
                    "selector": selector,
                    "selectorHint": field.get("selectorHint") or selector,
                    "filePath": value,
                    "fieldId": field.get("fieldId"),
                    "fieldLabel": field.get("label"),
                    "normalizedKey": field.get("normalizedKey"),
                    "fieldType": field.get("fieldType"),
                    "section": field.get("section"),
                    "valueRef": field.get("valueRef"),
                }
            )
            continue
        if value is None or str(value).strip() == "":
            continue
        actions.append(
            {
                "type": "fill_field",
                "selector": selector,
                "selectorHint": field.get("selectorHint") or selector,
                "value": value,
                "fieldId": field.get("fieldId"),
                "fieldLabel": field.get("label"),
                "normalizedKey": field.get("normalizedKey"),
                "fieldType": field.get("fieldType"),
                "section": field.get("section"),
                "valueRef": field.get("valueRef"),
            }
        )
    return normalize_replay_actions(actions)


def ensure_replay_plan(
    plan: dict[str, Any] | None,
    saved_fields: list[dict[str, Any]],
    *,
    nav_url: str,
    source_url: str = "",
    provider: str = "",
    use_iframe: bool = False,
    iframe_selector: str = "",
) -> dict[str, Any] | None:
    """Return a usable replay plan, rebuilding fill actions from saved fields when needed."""
    base = plan or {}
    actions = list(base.get("fillActions") or [])
    if actions and saved_fields:
        actions = merge_plan_actions_with_fields(actions, saved_fields)
    elif not actions and saved_fields:
        actions = build_replay_actions_from_fields(saved_fields)
    elif actions:
        actions = normalize_replay_actions(actions)
    if not actions:
        return None
    return build_browser_plan(
        nav_url=str(base.get("navUrl") or nav_url),
        source_url=str(base.get("sourceUrl") or source_url or nav_url),
        provider=str(base.get("provider") or provider),
        fill_actions=actions,
        use_iframe=bool(base.get("useIframe", use_iframe)),
        iframe_selector=str(base.get("iframeSelector") or iframe_selector or "iframe[src*='greenhouse.io']"),
        form_nav_url=str(base.get("formNavUrl") or ""),
    )


def autofill_state_metadata(draft: dict[str, Any], *, browser_open: bool = False) -> dict[str, Any]:
    """Explicit saved-state flags keyed by applicationId + jobId for UI and API consumers."""
    application_id = str(draft.get("id") or "")
    job_id = str(draft.get("jobId") or "")
    status = str(draft.get("status") or "")

    if status in {"submitted_manually", "archived"}:
        return {
            "applicationId": application_id,
            "jobId": job_id,
            "hasSavedAutofillState": False,
            "autofillStepCount": effective_autofill_step_count(draft),
            "quickApplyAvailable": False,
            "prepRequired": False,
            "quickApplyMode": "none",
            "quickApplyStepCount": 0,
            "quickApplyLabel": "Submitted" if status == "submitted_manually" else "Archived",
        }

    step_count = effective_autofill_step_count(draft)
    has_saved = step_count > 0

    if browser_open and has_saved:
        return {
            "applicationId": application_id,
            "jobId": job_id,
            "hasSavedAutofillState": True,
            "autofillStepCount": step_count,
            "quickApplyAvailable": True,
            "prepRequired": False,
            "quickApplyMode": "focus",
            "quickApplyStepCount": step_count,
            "quickApplyLabel": "Quick apply ready · Chrome open",
        }

    if has_saved:
        return {
            "applicationId": application_id,
            "jobId": job_id,
            "hasSavedAutofillState": True,
            "autofillStepCount": step_count,
            "quickApplyAvailable": True,
            "prepRequired": False,
            "quickApplyMode": "replay",
            "quickApplyStepCount": step_count,
            "quickApplyLabel": f"Quick apply ready · {step_count} saved step{'s' if step_count != 1 else ''}",
        }

    if status == "ready_to_prepare":
        label = "Not prepared — prep will retry automatically"
    elif status in {"needs_review", "in_progress", "blocked", "ready_for_final_review"}:
        label = "Preparing saved autofill state…"
    else:
        label = "Preparing in the background…"

    return {
        "applicationId": application_id,
        "jobId": job_id,
        "hasSavedAutofillState": False,
        "autofillStepCount": 0,
        "quickApplyAvailable": False,
        "prepRequired": True,
        "quickApplyMode": "none",
        "quickApplyStepCount": 0,
        "quickApplyLabel": label,
    }


def quick_apply_info(draft: dict[str, Any], *, browser_open: bool = False) -> dict[str, Any]:
    """Backward-compatible wrapper around autofill_state_metadata."""
    meta = autofill_state_metadata(draft, browser_open=browser_open)
    return {
        "quickApplyAvailable": meta["quickApplyAvailable"],
        "quickApplyMode": meta["quickApplyMode"],
        "quickApplyStepCount": meta["quickApplyStepCount"],
        "quickApplyLabel": meta["quickApplyLabel"],
        "hasSavedAutofillState": meta["hasSavedAutofillState"],
        "autofillStepCount": meta["autofillStepCount"],
        "prepRequired": meta["prepRequired"],
        "applicationId": meta["applicationId"],
        "jobId": meta["jobId"],
    }


def reconcile_stale_browser_run(
    db: Any,
    draft: dict[str, Any],
    *,
    active_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Clear orphaned in_progress browser runs so cards don't stay stuck."""
    from app.services.application_assistant.browser_runner import get_active_session
    from app.services.application_assistant.persistence import (
        get_active_browser_run_for_app,
        update_application_draft,
        update_browser_run,
    )
    from app.services.application_assistant.worker import task_status

    app_id = str(draft.get("id") or "")
    if not app_id:
        return draft

    if active_run is None:
        active_run = get_active_browser_run_for_app(db, app_id)
    if not active_run or active_run.get("status") != "running":
        return draft

    if get_active_session(app_id):
        return draft

    prep_running = task_status(f"qwen_prep_{app_id}") == "running"
    open_running = task_status(f"open_review_{app_id}") == "running"

    started_at = str(active_run.get("startedAt") or "")
    age_sec = _STALE_BROWSER_RUN_IDLE_SEC + 1
    try:
        t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        age_sec = (datetime.now(timezone.utc) - t).total_seconds()
    except (ValueError, TypeError):
        pass

    if prep_running or open_running:
        grace_sec = 12 if open_running else _STALE_BROWSER_RUN_IDLE_SEC
        if age_sec < grace_sec:
            return draft
    elif age_sec < 3:
        # Brief grace for registry/session teardown right after close.
        return draft

    update_browser_run(
        db,
        str(active_run.get("id") or ""),
        {
            "status": "stopped",
            "endedAt": now_iso(),
            "error": "Browser closed or run interrupted",
        },
    )

    has_saved = has_persisted_autofill_plan(draft)
    next_status = "needs_review" if has_saved else "ready_to_prepare"
    if draft.get("status") == "in_progress":
        update_application_draft(db, app_id, {"status": next_status})
        draft = {**draft, "status": next_status}

    return draft


def enrich_draft_list_summary(draft: dict[str, Any]) -> dict[str, Any]:
    """Lightweight list-row enrichment — metadata only, no plan rebuild or DB writes."""
    return {**draft, **autofill_state_metadata(draft)}


_LIST_HEAVY_KEYS = frozenset({
    "fields",
    "browserPlan",
    "prepLog",
    "screenshots",
    "skipped",
})


def summarize_application_list_item(draft: dict[str, Any]) -> dict[str, Any]:
    """Card-safe application row for list endpoints (drops large nested blobs)."""
    autofill_meta = autofill_state_metadata(draft)
    slim = {key: value for key, value in draft.items() if key not in _LIST_HEAVY_KEYS}
    return {**slim, **autofill_meta}


def enrich_draft_replay_state(draft: dict[str, Any], *, browser_open: bool = False) -> dict[str, Any]:
    """Attach autofill metadata; optionally hydrate replay plan values from saved fields."""
    fields = draft.get("fields") or []
    enriched = dict(draft)
    if has_persisted_autofill_plan(draft) and fields:
        rebuilt = ensure_replay_plan(
            draft.get("browserPlan"),
            fields,
            nav_url=str(draft.get("jobUrl") or ""),
            source_url=str(draft.get("jobUrl") or ""),
            provider=str(draft.get("provider") or ""),
        )
        if plan_is_usable(rebuilt):
            enriched["browserPlan"] = rebuilt
    return {**enriched, **autofill_state_metadata(enriched, browser_open=browser_open)}


def list_autofill_states(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize saved autofill state for every application draft."""
    return [
        {
            "applicationId": str(d.get("id") or ""),
            "jobId": str(d.get("jobId") or ""),
            "companyName": d.get("companyName", ""),
            "roleTitle": d.get("roleTitle", ""),
            "status": d.get("status", ""),
            "hasSavedAutofillState": has_persisted_autofill_plan(d),
            "autofillStepCount": int((d.get("browserPlan") or {}).get("actionCount") or 0),
        }
        for d in drafts
    ]


def sort_fill_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def order(action: dict[str, Any]) -> tuple[int, str]:
        if str(action.get("type") or "") == "upload_document":
            return (-1, str(action.get("fieldLabel") or ""))
        if action.get("normalizedKey") == "phone_country":
            return (2, str(action.get("fieldLabel") or ""))
        label = str(action.get("fieldLabel") or "").lower()
        if label.startswith("phone"):
            return (1, label)
        return (0, label)

    return sorted(actions, key=order)
