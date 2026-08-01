"""Collect and persist user answers for unrecognized application fields."""

from __future__ import annotations

import json
import re
from typing import Any

from app.db.store import get_kv, now_iso, set_kv
from app.services.application_assistant.field_options import normalize_field_options, sanitize_options_for_field
from app.services.application_assistant.answer_classification import (
    AnswerClassification,
    classify_answer,
    detect_sensitivity,
    match_profile_key,
    normalize_field_key,
)
from app.services.application_assistant.document_files import is_cover_letter_field, is_resume_field
from app.services.application_assistant.domain import SensitivityCategory
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import (
    delete_answer,
    get_application_draft,
    get_settings,
    list_answer_library,
    list_application_drafts,
    save_application_fields,
    update_application_draft,
    upsert_answer,
)


def _log_analyze(
    summary: str,
    *,
    event_type: str = "analyze_progress",
    application_id: str | None = None,
    company_name: str = "",
    metadata: dict[str, Any] | None = None,
    success: bool = True,
    error: str = "",
    latency_ms: int = 0,
    count_as_request: bool = False,
) -> None:
    from app.services.application_assistant.qwen_activity import log_activity_event

    meta = dict(metadata or {})
    if application_id:
        meta.setdefault("applicationId", application_id)
    if company_name:
        meta.setdefault("companyName", company_name)
    log_activity_event(
        event_type=event_type,
        summary=summary,
        success=success,
        error=error,
        latency_ms=latency_ms,
        metadata=meta,
        count_as_request=count_as_request,
    )

MANUAL_ONLY_LABEL_RE = re.compile(
    r"captcha|recaptcha|g-recaptcha|electronic\s+sign|signature|verify\s+you\s+are\s+human",
    re.I,
)

FILE_UPLOAD_LABEL_RE = re.compile(
    r"^attach$|\battach\b|\bupload\b|resume|curriculum\s*vitae|\bcv\b|cover\s*letter",
    re.I,
)

VAGUE_WIZARD_LABEL_RE = re.compile(
    r"^search$|please\s+specify|if\s*\([^)]*\)\s*other|please\s+explain|^other$|^specify$",
    re.I,
)

PLACEHOLDER_ANSWER_VALUES = frozenset({"-", "—", "", "na", "n/a", "none", "null"})


def _normalize_label(label: str) -> str:
    return re.sub(r"\*+$", "", label.strip()).lower()


def _is_document_upload_field(field: dict[str, Any]) -> bool:
    label = str(field.get("label") or "")
    name = str(field.get("name") or "")
    field_type = str(field.get("fieldType") or "").lower()
    if field_type == "file":
        return True
    text = f"{label} {name}".lower()
    return bool(FILE_UPLOAD_LABEL_RE.search(text))


def _is_vague_wizard_field(field: dict[str, Any]) -> bool:
    """Fields too ambiguous for the wizard — handle in browser instead."""
    if _is_document_upload_field(field):
        return True
    label = _normalize_label(str(field.get("label") or ""))
    if not label:
        norm = _normalize_label(str(field.get("normalizedKey") or "").replace("_", " "))
        label = norm
    if not label:
        return True
    if VAGUE_WIZARD_LABEL_RE.search(label):
        return True
    if label in {"search", "attach", "other", "specify", "please specify"}:
        return True
    return False


def _is_placeholder_answer(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in PLACEHOLDER_ANSWER_VALUES


def _sanitize_misleading_user_answers(fields: list[dict[str, Any]]) -> int:
    """Drop placeholder answers saved for vague/conditional fields (e.g. '-' for 'Attach')."""
    cleared = 0
    for field in fields:
        if not _is_vague_wizard_field(field):
            continue
        if not _is_placeholder_answer(field.get("proposedValue")):
            continue
        field.update(
            {
                "classification": AnswerClassification.UNKNOWN.value,
                "proposedValue": None,
                "confidence": 0.0,
                "source": "",
                "userProvided": False,
                "requiresUserReview": True,
            }
        )
        cleared += 1
    return cleared


def _prune_misleading_answer_library(db: Any, answer_library: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove placeholder answers tied to vague form labels (e.g. '-' saved for 'Search')."""
    kept: list[dict[str, Any]] = []
    for entry in answer_library:
        variants = [str(v) for v in entry.get("questionVariants") or [] if str(v).strip()]
        pseudo_field = {
            "label": variants[0] if variants else "",
            "normalizedKey": entry.get("normalizedKey"),
        }
        if _is_placeholder_answer(entry.get("value")) and _is_vague_wizard_field(pseudo_field):
            if entry.get("id"):
                delete_answer(db, str(entry["id"]))
            continue
        kept.append(entry)
    return kept


STORAGE_INFER_SYSTEM = """You interpret messy job application form fields before showing them to a user.

Employer ATS forms often have vague labels like "Attach", "Search", "Please specify", or "If Other, please explain".
Use section, help text, field type, and options to infer what the employer is really asking.

Return JSON only:
{
  "fields": [
    {
      "fieldId": "<same id from input>",
      "displayTitle": "<clear question the user should answer>",
      "displayContext": "<optional extra context, or empty string>",
      "wizardEligible": true,
      "profileKey": "<one of the supplied profile keys, or null>",
      "normalizedKey": "<snake_case stable key for answer library>",
      "sensitivityCategory": "<none|demographic|disability|veteran|work_authorization|immigration|salary|...>",
      "reason": "<short note on interpretation and storage>"
    }
  ]
}

Rules:
- wizardEligible=false for: file uploads, captcha, pure UI chrome (search boxes, filters), conditional follow-ups that depend on a prior answer you cannot see
- wizardEligible=true for real screening, demographic, or application questions even when the raw label is vague
- fieldType checkbox: wizardEligible=true, displayTitle should state what checking the box means (e.g. consent to demographic data processing); user will check a box, not type text
- fieldType search or label "Search": wizardEligible=false (phone country search UI — handle in browser)
- Never invent or guess answer values — only clarify what is being asked and where to store the answer
- displayTitle must be a complete, understandable question (not the raw label unless it is already clear)
- Use profileKey when the question maps to gender, veteran status, disability, ethnicity, work authorization, sponsorship, or similar standard profile fields"""

PROFILE_KEY_TO_SCREENING_ID: dict[str, str] = {
    "gender": "gender-identity",
    "transgender": "transgender-identity",
    "raceEthnicity": "racial-ethnic-background",
    "sexualOrientation": "sexual-orientation",
    "workAuthorization": "us-work-authorization",
    "sponsorship": "visa-sponsorship-needed",
    "veteran": "veteran-status",
    "disability": "disability-status",
}

STANDARD_PROFILE_KEYS = frozenset(
    {
        "gender",
        "transgender",
        "raceEthnicity",
        "hispanic",
        "veteran",
        "disability",
        "sexualOrientation",
        "pronouns",
        "workAuthorization",
        "sponsorship",
        "salaryExpectations",
    }
)


def _field_identity(field: dict[str, Any]) -> str:
    return str(field.get("fieldId") or field.get("normalizedKey") or field.get("label") or "")


def _resolve_field_for_submission(
    fields: list[dict[str, Any]],
    *,
    field_id: str,
    norm_key: str,
) -> dict[str, Any] | None:
    """Match a wizard submission to a draft field by id or normalized key."""
    by_id = {_field_identity(f): f for f in fields}
    by_norm = {str(f.get("normalizedKey") or ""): f for f in fields if f.get("normalizedKey")}

    if field_id and field_id in by_id:
        return by_id[field_id]
    if norm_key and norm_key in by_norm:
        return by_norm[norm_key]

    if field_id:
        for f in fields:
            fid = str(f.get("fieldId") or "")
            if fid and (fid == field_id or fid.startswith(field_id) or field_id.startswith(fid)):
                return f
    if norm_key:
        for f in fields:
            nk = str(f.get("normalizedKey") or "")
            if nk and (nk == norm_key or nk.startswith(norm_key) or norm_key.startswith(nk)):
                return f
    return None


def _normalize_submitted_value(field: dict[str, Any], value: str) -> str:
    """Normalize wizard values for storage (checkbox → yes/no)."""
    text = str(value or "").strip()
    field_type = str(field.get("fieldType") or "").lower()
    if field_type == "checkbox":
        lower = text.lower()
        if lower in {"yes", "true", "checked", "on", "1", "i consent", "consent"}:
            return "yes"
        if lower in {"no", "false", "unchecked", "off", "0"}:
            return "no"
    return text


def _should_gate_field(field: dict[str, Any], *, documents: dict[str, Any] | None = None) -> bool:
    """Whether this field must be answered in profile before opening the browser."""
    classification = field.get("classification", "unknown")
    if classification in ("verified", "manual_only"):
        return False

    label = str(field.get("label") or "")
    norm = str(field.get("normalizedKey") or "")
    if norm == "g-recaptcha-response" or MANUAL_ONLY_LABEL_RE.search(label):
        return False

    if _is_document_upload_field(field):
        return False

    if _is_vague_wizard_field(field):
        return False

    field_type = str(field.get("fieldType") or "").lower()
    name = str(field.get("name") or "")
    if field_type == "file":
        if is_resume_field(label, name, field_type) and documents and documents.get("defaultResume"):
            return False
        if is_cover_letter_field(label, name, field_type) and documents and documents.get("defaultCoverLetter"):
            return False

    return classification in ("unknown", "inferred", "conflict")


def reclassify_draft_fields(
    fields: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
    answer_library: list[dict[str, Any]],
    documents: dict[str, Any] | None = None,
    allow_inferred: bool = False,
) -> list[dict[str, Any]]:
    """Re-run classification now that profile / answer library may have new values."""
    for field in fields:
        if field.get("classification") == AnswerClassification.MANUAL_ONLY.value:
            continue
        label = str(field.get("label") or "")
        classification, value, confidence, source, sensitivity = classify_answer(
            label=label,
            help_text=str(field.get("helpText") or ""),
            field_type=str(field.get("fieldType") or ""),
            profile=profile,
            answer_library=answer_library,
            allow_inferred=allow_inferred,
            name=str(field.get("name") or ""),
            field_id=str(field.get("fieldId") or field.get("id") or ""),
            selector_hint=str(field.get("selectorHint") or ""),
        )
        if classification == AnswerClassification.VERIFIED:
            field.update(
                {
                    "classification": classification.value,
                    "proposedValue": value,
                    "confidence": confidence,
                    "source": source,
                    "sensitivityCategory": sensitivity.value,
                    "requiresUserReview": False,
                }
            )
    return fields


def list_pending_fields(
    draft: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    documents: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fields that still need a user-provided answer before opening the browser."""
    pending: list[dict[str, Any]] = []
    for field in draft.get("fields") or []:
        if not _should_gate_field(field, documents=documents):
            continue

        label = str(field.get("label") or "")
        profile_key = match_profile_key(label)
        options = sanitize_options_for_field(field, field.get("options") or [])
        pending.append(
            {
                "fieldId": field.get("fieldId") or field.get("normalizedKey") or normalize_field_key(label),
                "label": label,
                "normalizedKey": field.get("normalizedKey") or normalize_field_key(label),
                "fieldType": field.get("fieldType", "text"),
                "required": bool(field.get("required")),
                "options": options,
                "section": field.get("section", ""),
                "helpText": field.get("helpText") or "",
                "sensitivityCategory": field.get("sensitivityCategory", "none"),
                "selectorHint": field.get("selectorHint", ""),
                "suggestedProfileKey": profile_key,
            }
        )
    pending.sort(key=lambda f: (not f.get("required"), f.get("label", "")))
    return pending


def categorize_pending_field(field: dict[str, Any]) -> str:
    """profile = reusable screening answer; application = employer-specific."""
    profile_key = field.get("suggestedProfileKey")
    if profile_key and profile_key in STANDARD_PROFILE_KEYS:
        return "profile"
    return "application"


def split_pending_fields(pending: list[dict[str, Any]]) -> dict[str, Any]:
    """Split pending fields into profile vs application-specific buckets."""
    profile_pending: list[dict[str, Any]] = []
    application_pending: list[dict[str, Any]] = []
    profile_keys: set[str] = set()

    for field in pending:
        categorized = {**field, "category": categorize_pending_field(field)}
        if categorized["category"] == "profile":
            profile_pending.append(categorized)
            if field.get("suggestedProfileKey"):
                profile_keys.add(str(field["suggestedProfileKey"]))
        else:
            application_pending.append(categorized)

    return {
        "pending": profile_pending + application_pending,
        "profilePending": profile_pending,
        "applicationPending": application_pending,
        "profileKeysMissing": sorted(profile_keys),
    }


def persist_wizard_analysis(
    db: Any,
    app_id: str,
    split: dict[str, Any],
    *,
    ai_analyzed: bool = True,
) -> None:
    """Persist Qwen analysis results and wizard question cache on the application draft."""
    pending = list(split.get("pending") or [])
    update_application_draft(
        db,
        app_id,
        {
            "aiAnalyzed": ai_analyzed,
            "aiAnalyzedAt": now_iso(),
            "pendingFieldCount": len(pending),
            "readyForBrowser": len(pending) == 0,
            "wizardPendingCache": {
                "pending": pending,
                "profilePending": list(split.get("profilePending") or []),
                "applicationPending": list(split.get("applicationPending") or []),
                "profileKeysMissing": list(split.get("profileKeysMissing") or []),
            },
        },
    )


def refresh_wizard_cache_from_readiness(
    draft: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any] | None:
    """Filter persisted wizard cache to fields that are still pending."""
    if not draft.get("aiAnalyzed"):
        return None
    cache = draft.get("wizardPendingCache")
    if not isinstance(cache, dict):
        return None

    still_pending_ids = {
        str(field.get("fieldId") or "")
        for field in readiness.get("pending") or []
        if field.get("fieldId")
    }

    def keep(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [
            field
            for field in (items or [])
            if str(field.get("fieldId") or "") in still_pending_ids
        ]

    profile_pending = keep(cache.get("profilePending"))
    application_pending = keep(cache.get("applicationPending"))
    pending = keep(cache.get("pending")) or profile_pending + application_pending
    pending = filter_wizard_pending(pending)
    profile_pending = filter_wizard_pending(profile_pending)
    application_pending = filter_wizard_pending(application_pending)

    return {
        "pending": pending,
        "profilePending": profile_pending,
        "applicationPending": application_pending,
        "profileKeysMissing": list(cache.get("profileKeysMissing") or []),
    }


def load_persisted_wizard_pending(
    db: Any,
    app_id: str,
    readiness: dict[str, Any],
) -> dict[str, Any] | None:
    """Load cached wizard questions for an already-analyzed application."""
    draft = get_application_draft(db, app_id)
    if not draft:
        return None
    split = refresh_wizard_cache_from_readiness(draft, readiness)
    if split is None:
        return None
    persist_wizard_analysis(db, app_id, split, ai_analyzed=True)
    return split


def register_profile_questions(
    profile: dict[str, Any],
    pending: list[dict[str, Any]],
    *,
    app_id: str,
) -> dict[str, Any]:
    """Sync unanswered application questions onto the user profile for the dashboard."""
    profile = dict(profile)
    profile["applicationQuestions"] = [
        {
            "id": item.get("normalizedKey") or item.get("fieldId"),
            "label": item.get("label"),
            "options": item.get("options") or [],
            "fieldType": item.get("fieldType", "text"),
            "profileKey": item.get("suggestedProfileKey"),
            "required": bool(item.get("required")),
            "sourceApplicationId": app_id,
            "updatedAt": now_iso(),
        }
        for item in pending
    ]
    return profile


def sync_application_readiness(
    db: Any,
    app_id: str,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Reclassify fields, register profile questions, and update draft browser gate flags."""
    draft = get_application_draft(db, app_id)
    if not draft:
        return {"readyForBrowser": False, "pendingCount": 0, "pending": []}

    profile = dict(get_kv(db, "profile") or {})
    documents = get_kv(db, "documents") or {}
    answer_library = list_answer_library(db)
    answer_library = _prune_misleading_answer_library(db, answer_library)
    settings = get_settings(db)
    allow_inferred = bool(settings.get("allowInferredAnswers", False))

    fields = reclassify_draft_fields(
        list(draft.get("fields") or []),
        profile=profile,
        answer_library=answer_library,
        documents=documents,
        allow_inferred=allow_inferred,
    )
    _sanitize_misleading_user_answers(fields)
    fields = reclassify_draft_fields(
        fields,
        profile=profile,
        answer_library=answer_library,
        documents=documents,
        allow_inferred=allow_inferred,
    )
    pending = list_pending_fields({"fields": fields}, profile=profile, documents=documents)
    profile = register_profile_questions(profile, pending, app_id=app_id)

    ready = len(pending) == 0
    split = split_pending_fields(pending)
    if persist:
        set_kv(db, "profile", profile)
        save_application_fields(db, app_id, fields)
        draft_after = get_application_draft(db, app_id) or draft
        if draft_after.get("aiAnalyzed"):
            cached = refresh_wizard_cache_from_readiness(draft_after, {"pending": pending})
            if cached is not None:
                persist_wizard_analysis(db, app_id, cached, ai_analyzed=True)
            else:
                update_application_draft(
                    db,
                    app_id,
                    {
                        "readyForBrowser": ready,
                        "pendingFieldCount": len(pending),
                    },
                )
        else:
            update_application_draft(
                db,
                app_id,
                {
                    "readyForBrowser": ready,
                    "pendingFieldCount": len(pending),
                },
            )

    return {
        "readyForBrowser": ready,
        "pendingCount": len(pending),
        "pending": split["pending"],
        "profilePending": split["profilePending"],
        "applicationPending": split["applicationPending"],
        "profileKeysMissing": split["profileKeysMissing"],
    }


async def sync_application_readiness_async(
    db: Any,
    app_id: str,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    """Like sync_application_readiness, but uses AI semantic matching for paraphrased labels."""
    draft = get_application_draft(db, app_id)
    if not draft:
        return {"readyForBrowser": False, "pendingCount": 0, "pending": []}

    profile = dict(get_kv(db, "profile") or {})
    documents = get_kv(db, "documents") or {}
    answer_library = list_answer_library(db)
    answer_library = _prune_misleading_answer_library(db, answer_library)
    settings = get_settings(db)
    allow_inferred = bool(settings.get("allowInferredAnswers", False))

    fields = reclassify_draft_fields(
        list(draft.get("fields") or []),
        profile=profile,
        answer_library=answer_library,
        documents=documents,
        allow_inferred=allow_inferred,
    )
    _sanitize_misleading_user_answers(fields)
    fields = reclassify_draft_fields(
        fields,
        profile=profile,
        answer_library=answer_library,
        documents=documents,
        allow_inferred=allow_inferred,
    )

    from app.services.application_assistant.semantic_field_resolution import (
        persist_learned_variants,
        resolve_unknown_fields_semantically,
    )

    company = str(draft.get("companyName") or "")
    unknown_before = sum(1 for f in fields if f.get("classification") == "unknown")
    _log_analyze(
        f"Scanning {len(fields)} saved fields ({unknown_before} unknown) for semantic matches…",
        application_id=app_id,
        company_name=company,
    )

    context = {
        "profile": profile,
        "answerLibrary": answer_library,
        "documents": documents,
        "allowInferred": allow_inferred,
    }
    fields, semantic_report = await resolve_unknown_fields_semantically(
        fields,
        context,
        settings,
        analyze_context={"applicationId": app_id, "companyName": company},
    )
    matched = semantic_report.get("matched") or []
    if matched:
        labels = ", ".join(str(m.get("label") or "")[:40] for m in matched[:4])
        _log_analyze(
            f"Matched {len(matched)} field(s) to saved answers: {labels}{'…' if len(matched) > 4 else ''}",
            application_id=app_id,
            company_name=company,
        )
    elif unknown_before:
        _log_analyze(
            f"No semantic matches — {unknown_before} field(s) still need your answers",
            application_id=app_id,
            company_name=company,
        )
    if semantic_report.get("matched") and persist:
        persist_learned_variants(
            db,
            fields,
            upsert_answer=upsert_answer,
            list_answer_library=list_answer_library,
        )

    pending = list_pending_fields({"fields": fields}, profile=profile, documents=documents)
    profile = register_profile_questions(profile, pending, app_id=app_id)

    ready = len(pending) == 0
    split = split_pending_fields(pending)
    if persist:
        set_kv(db, "profile", profile)
        save_application_fields(db, app_id, fields)
        draft_after = get_application_draft(db, app_id) or draft
        if draft_after.get("aiAnalyzed"):
            cached = refresh_wizard_cache_from_readiness(draft_after, {"pending": pending})
            if cached is not None:
                persist_wizard_analysis(db, app_id, cached, ai_analyzed=True)
            else:
                update_application_draft(
                    db,
                    app_id,
                    {
                        "readyForBrowser": ready,
                        "pendingFieldCount": len(pending),
                    },
                )
        else:
            update_application_draft(
                db,
                app_id,
                {
                    "readyForBrowser": ready,
                    "pendingFieldCount": len(pending),
                },
            )

    return {
        "readyForBrowser": ready,
        "pendingCount": len(pending),
        "pending": split["pending"],
        "profilePending": split["profilePending"],
        "applicationPending": split["applicationPending"],
        "profileKeysMissing": split["profileKeysMissing"],
        "semanticMatches": semantic_report.get("matched", []),
    }


async def finalize_post_prep_field_analysis(
    db: Any,
    app_id: str,
    readiness: dict[str, Any],
    *,
    analyze_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich pending questions with Qwen and mark the draft analyzed after prep."""
    draft = get_application_draft(db, app_id) or {}
    company = str(draft.get("companyName") or "")
    ctx = analyze_context or {"applicationId": app_id, "companyName": company}
    pending = readiness.get("pending") or []

    if pending:
        profile = get_kv(db, "profile") or {}
        settings = get_settings(db)
        enriched = await enrich_pending_with_qwen(
            pending,
            profile,
            settings,
            analyze_context=ctx,
        )
        wizard_pending = filter_wizard_pending(enriched)
        split = split_pending_fields(wizard_pending)
    else:
        split = split_pending_fields(pending)
        wizard_pending = []

    persist_wizard_analysis(db, app_id, split, ai_analyzed=True)
    _log_analyze(
        f"Post-prep field analysis — {len(wizard_pending)} wizard question(s) for {company}",
        event_type="analyze_complete",
        application_id=app_id,
        company_name=company,
        metadata={"questionCount": len(wizard_pending)},
    )
    return {
        "readyForBrowser": len(wizard_pending) == 0,
        "pendingCount": len(split["pending"]),
        **split,
    }


def _profile_keys_for_prompt(profile: dict[str, Any]) -> list[str]:
    keys = sorted(STANDARD_PROFILE_KEYS)
    populated = [k for k in keys if str(profile.get(k) or "").strip()]
    return keys if not populated else keys


def _fallback_display_title(field: dict[str, Any]) -> str:
    label = str(field.get("label") or "").strip()
    lower = _normalize_label(label)
    if _is_document_upload_field(field):
        return "Upload your resume or document"
    fallback_titles = {
        "attach": "Upload your resume or document",
        "search": "Search field (handled in the browser, not here)",
        "please specify": "Provide additional details (if required by a prior answer)",
        "other": "If you selected Other, please explain",
        "specify": "Please specify additional details",
    }
    if lower in fallback_titles:
        return fallback_titles[lower]
    if VAGUE_WIZARD_LABEL_RE.search(lower):
        return label or "Additional information"
    return label or "Question"


def _fallback_enrich_field(field: dict[str, Any]) -> dict[str, Any]:
    """Heuristic interpretation when the LLM is unavailable."""
    copy = dict(field)
    label = str(field.get("label") or "")
    norm = str(field.get("normalizedKey") or "")
    field_type = str(field.get("fieldType") or "").lower()
    lower_label = _normalize_label(label)

    if norm == "g-recaptcha-response" or MANUAL_ONLY_LABEL_RE.search(label):
        copy["wizardEligible"] = False
    elif field_type == "search" or lower_label == "search":
        copy["wizardEligible"] = False
        copy["displayTitle"] = "Search box (handled in the browser when filling the form)"
    elif _is_document_upload_field(field) or _is_vague_wizard_field(field):
        copy["wizardEligible"] = False
    elif field_type == "checkbox" or "consent" in lower_label or "checking this box" in lower_label:
        copy["wizardEligible"] = True
        copy["displayTitle"] = _fallback_display_title(field) or label or "Consent required"
        copy["displayContext"] = "Check the box to consent — CareerOS will check it when filling the form."
    elif "privacy policy" in lower_label or "i understand my application" in lower_label:
        copy["wizardEligible"] = True
        copy["fieldType"] = "checkbox"
        copy["options"] = []
        copy["displayTitle"] = _fallback_display_title(field) or label or "Privacy policy acknowledgment"
        copy["displayContext"] = "Confirm you understand the employer privacy policy."
    else:
        copy["wizardEligible"] = True
        profile_key = field.get("suggestedProfileKey") or match_profile_key(label)
        if profile_key and profile_key in STANDARD_PROFILE_KEYS:
            copy["suggestedProfileKey"] = profile_key
    if not copy.get("displayTitle"):
        copy["displayTitle"] = _fallback_display_title(field)
    help_text = str(field.get("helpText") or "").strip()
    section = str(field.get("section") or "").strip()
    context_parts = [p for p in [help_text, f"Section: {section}" if section else ""] if p]
    if not copy.get("displayContext"):
        copy["displayContext"] = " · ".join(context_parts)
    return copy


def _apply_enrichment_hint(field: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    copy = dict(field)
    if hint.get("displayTitle"):
        copy["displayTitle"] = str(hint["displayTitle"]).strip()
    if hint.get("displayContext") is not None:
        copy["displayContext"] = str(hint.get("displayContext") or "").strip()
    if "wizardEligible" in hint:
        copy["wizardEligible"] = bool(hint["wizardEligible"])
    if hint.get("profileKey") and str(hint["profileKey"]) in STANDARD_PROFILE_KEYS:
        copy["suggestedProfileKey"] = str(hint["profileKey"])
    if hint.get("normalizedKey"):
        copy["suggestedNormalizedKey"] = str(hint["normalizedKey"])
    if hint.get("sensitivityCategory"):
        copy["sensitivityCategory"] = str(hint["sensitivityCategory"])
    if hint.get("reason"):
        copy["storageHint"] = str(hint["reason"])
    if _is_vague_wizard_field(copy):
        copy["wizardEligible"] = False
    return copy


def _sanitize_wizard_field(field: dict[str, Any]) -> dict[str, Any]:
    """Fix leaked phone-country options and infer better input types for the wizard."""
    copy = dict(field)
    copy["options"] = sanitize_options_for_field(copy, copy.get("options") or [])

    label = str(copy.get("label") or "")
    display = str(copy.get("displayTitle") or label)
    combined = f"{label} {display}".lower()

    if any(
        phrase in combined
        for phrase in (
            "privacy policy",
            "i understand",
            "i agree",
            "consent",
            "checking this box",
            "candidate privacy",
        )
    ):
        copy["fieldType"] = "checkbox"
        copy["options"] = []
    elif any(phrase in combined for phrase in ("languages", "speak fluently", "fluent in")):
        copy["options"] = []
        copy["fieldType"] = "text"
    elif any(phrase in combined for phrase in ("cities", "available to work", "where are you located")):
        copy["options"] = []
        copy["fieldType"] = "text"

    return copy


def filter_wizard_pending(pending: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only questions the AI (or fallback) marked as wizard-eligible."""
    return [
        _sanitize_wizard_field(field)
        for field in pending
        if field.get("wizardEligible", True) and not _is_vague_wizard_field(field)
    ]


def _field_payload_for_enrichment(field: dict[str, Any]) -> dict[str, Any]:
    options = field.get("options") or []
    return {
        "fieldId": field["fieldId"],
        "label": field.get("label"),
        "helpText": field.get("helpText") or "",
        "section": field.get("section") or "",
        "fieldType": field.get("fieldType") or "text",
        "required": bool(field.get("required")),
        "options": options[:12],
    }


async def enrich_pending_with_qwen(
    pending: list[dict[str, Any]],
    profile: dict[str, Any],
    settings: dict[str, Any],
    *,
    analyze_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Use Qwen to interpret every pending field before showing it in the wizard."""
    if not pending:
        return pending

    ctx = analyze_context or {}
    app_id = str(ctx.get("applicationId") or "")
    company = str(ctx.get("companyName") or "")

    client = create_llm_client(settings)
    if not client.enabled:
        _log_analyze(
            "Qwen offline — using fallback labels for pending fields",
            application_id=app_id or None,
            company_name=company,
            success=False,
        )
        return [_fallback_enrich_field(field) for field in pending]

    profile_keys = _profile_keys_for_prompt(profile)
    hints_by_id: dict[str, dict[str, Any]] = {}
    batch_size = 15
    total_batches = (len(pending) + batch_size - 1) // batch_size

    for batch_num, start in enumerate(range(0, len(pending), batch_size), start=1):
        batch = pending[start : start + batch_size]
        labels = [str(f.get("label") or "Untitled")[:50] for f in batch]
        preview = "; ".join(labels[:3])
        _log_analyze(
            f"Qwen batch {batch_num}/{total_batches}: interpreting {len(batch)} field(s) — {preview}{'…' if len(batch) > 3 else ''}",
            event_type="analyze_llm",
            application_id=app_id or None,
            company_name=company,
            metadata={"batch": batch_num, "totalBatches": total_batches, "fieldLabels": labels},
        )
        prompt = (
            "Interpret each application form field for a user-facing wizard.\n"
            f"Available profile keys: {json.dumps(profile_keys)}\n\n"
            "Fields:\n"
            + json.dumps([_field_payload_for_enrichment(field) for field in batch], indent=2)
            + '\n\nReturn JSON: {"fields":[{"fieldId":"...","displayTitle":"...","displayContext":"...",'
            '"wizardEligible":true,"profileKey":null,"normalizedKey":"...","sensitivityCategory":"...","reason":"..."}]}'
        )
        import time

        t0 = time.perf_counter()
        result = await client.complete(prompt, system=STORAGE_INFER_SYSTEM, response_schema={"type": "object"})
        latency = int((time.perf_counter() - t0) * 1000)
        if not result.get("success"):
            _log_analyze(
                f"Qwen batch {batch_num} failed: {result.get('error', 'unknown error')}",
                event_type="analyze_llm",
                application_id=app_id or None,
                company_name=company,
                success=False,
                error=str(result.get("error") or ""),
                latency_ms=latency,
                count_as_request=True,
            )
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        interpreted: list[str] = []
        for item in data.get("fields") or []:
            field_id = str(item.get("fieldId") or "")
            if field_id:
                hints_by_id[field_id] = item
                title = str(item.get("displayTitle") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if title:
                    interpreted.append(f"“{title}”" + (f" ({reason[:60]})" if reason else ""))
        _log_analyze(
            f"Qwen batch {batch_num} done ({latency}ms): "
            + ("; ".join(interpreted[:3]) if interpreted else "no titles returned")
            + ("…" if len(interpreted) > 3 else ""),
            event_type="analyze_llm",
            application_id=app_id or None,
            company_name=company,
            latency_ms=latency,
            count_as_request=True,
            metadata={"responsePreview": "; ".join(interpreted[:5])},
        )

    enriched: list[dict[str, Any]] = []
    for field in pending:
        hint = hints_by_id.get(str(field.get("fieldId")))
        if hint:
            enriched.append(_apply_enrichment_hint(field, hint))
        else:
            enriched.append(_fallback_enrich_field(field))
    return enriched


def _sync_screening_answer(profile: dict[str, Any], profile_key: str, label: str, value: str) -> None:
    screening_id = PROFILE_KEY_TO_SCREENING_ID.get(profile_key)
    if not screening_id:
        return

    entries = list(profile.get("screeningAnswers") or [])
    norm_label = normalize_field_key(label)
    updated = False
    for entry in entries:
        if entry.get("id") == screening_id:
            entry["answer"] = value
            entry["question"] = label or entry.get("question", "")
            variants = list(entry.get("matchPatterns") or [])
            if norm_label and norm_label not in variants:
                variants.append(norm_label)
            entry["matchPatterns"] = variants
            updated = True
            break

    if not updated:
        entries.append(
            {
                "id": screening_id,
                "question": label,
                "answer": value,
                "matchPatterns": [norm_label] if norm_label else [],
            }
        )
    profile["screeningAnswers"] = entries


def _sensitivity_to_category(sensitivity: SensitivityCategory) -> str:
    mapping = {
        SensitivityCategory.WORK_AUTHORIZATION: "work_authorization",
        SensitivityCategory.IMMIGRATION: "immigration",
        SensitivityCategory.DISABILITY: "disability",
        SensitivityCategory.VETERAN: "veteran",
        SensitivityCategory.DEMOGRAPHIC: "demographic",
        SensitivityCategory.SALARY: "salary",
    }
    return mapping.get(sensitivity, "none")


def save_field_answers(
    db: Any,
    app_id: str,
    submissions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Persist user answers to profile + answer library and update the application draft."""
    draft = get_application_draft(db, app_id)
    if not draft:
        return None

    profile = dict(get_kv(db, "profile") or {})
    fields = list(draft.get("fields") or [])

    saved_count = 0
    for submission in submissions:
        value = submission.get("value")
        if value is None or not str(value).strip():
            continue

        field_id = str(submission.get("fieldId") or "")
        norm_key = str(submission.get("normalizedKey") or "")
        field = _resolve_field_for_submission(fields, field_id=field_id, norm_key=norm_key)
        if not field:
            continue

        label = str(field.get("label") or "")
        text_value = _normalize_submitted_value(field, str(value).strip())
        if _is_placeholder_answer(text_value) and not field.get("options"):
            continue

        profile_key = (
            submission.get("profileKey")
            or field.get("suggestedProfileKey")
            or match_profile_key(label)
        )
        if profile_key and profile_key not in STANDARD_PROFILE_KEYS:
            profile_key = None

        sensitivity = detect_sensitivity(label, str(field.get("helpText") or ""))
        sensitivity_category = _sensitivity_to_category(sensitivity)

        if profile_key:
            profile[profile_key] = text_value
            _sync_screening_answer(profile, profile_key, label, text_value)

        library_key = norm_key or field.get("normalizedKey") or normalize_field_key(label)
        field_type = str(field.get("fieldType") or "").lower()
        existing_answer = next(
            (a for a in list_answer_library(db) if a.get("normalizedKey") == library_key),
            None,
        )
        answer_payload: dict[str, Any] = {
            "normalizedKey": library_key,
            "questionVariants": [label] if label else [],
            "answerType": "checkbox" if field_type == "checkbox" else ("select" if field.get("options") else "short_text"),
            "value": text_value,
            "sensitivityCategory": sensitivity_category,
            "verificationStatus": "verified",
            "source": "user_provided",
        }
        if existing_answer:
            answer_payload["id"] = existing_answer["id"]
            variants = list(existing_answer.get("questionVariants") or [])
            if label and label not in variants:
                variants.append(label)
            answer_payload["questionVariants"] = variants
        upsert_answer(db, answer_payload)

        field.update(
            {
                "classification": "verified",
                "proposedValue": text_value,
                "confidence": 1.0,
                "source": f"profile.{profile_key}" if profile_key else f"answer_library.{library_key}",
                "filled": False,
                "userProvided": True,
                "requiresUserReview": False,
            }
        )
        saved_count += 1

    if saved_count:
        set_kv(db, "profile", profile)
        save_application_fields(db, app_id, fields)

    readiness = sync_application_readiness(db, app_id, persist=True)
    updated = get_application_draft(db, app_id)
    if updated:
        updated["readyForBrowser"] = readiness["readyForBrowser"]
        if updated.get("aiAnalyzed"):
            split = refresh_wizard_cache_from_readiness(updated, readiness)
            if split is not None:
                persist_wizard_analysis(db, app_id, split, ai_analyzed=True)
                updated = get_application_draft(db, app_id) or updated
            else:
                updated["pendingFieldCount"] = readiness["pendingCount"]
        else:
            updated["pendingFieldCount"] = readiness["pendingCount"]
    updated = updated or {}
    updated["savedCount"] = saved_count
    return updated


DEDUPE_SYSTEM = """You normalize and deduplicate job application form fields collected from multiple employers.

Many applications ask the same question with different wording (e.g. "Gender", "What gender do you identify as?", "Gender identity").
Cluster semantically identical fields into ONE canonical question the user answers once.

Return JSON only:
{
  "questions": [
    {
      "canonicalId": "<stable snake_case id>",
      "displayTitle": "<one clear normalized question>",
      "displayContext": "<optional helpful context, or empty string>",
      "wizardEligible": true,
      "profileKey": "<standard profile key or null>",
      "normalizedKey": "<answer library snake_case key>",
      "sensitivityCategory": "<none|demographic|disability|veteran|work_authorization|immigration|salary|...>",
      "fieldIds": ["<fieldId values from input — every fieldId must appear in exactly one cluster>"],
      "variantLabels": ["<original employer labels in this cluster>"]
    }
  ]
}

Rules:
- Every input fieldId must appear in exactly one cluster
- Do NOT merge fields that ask different things (e.g. veteran status vs disability status)
- wizardEligible=false only for file uploads, captcha, or pure UI chrome
- displayTitle must be a complete question understandable without seeing the raw employer label
- Never invent answer values — only normalize and deduplicate questions"""


def _merge_occurrence_options(items: list[dict[str, Any]]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in items:
        for opt in normalize_field_options(item.get("options") or []):
            key = opt.lower()
            if key not in seen:
                seen.add(key)
                merged.append(opt)
    return merged


def _build_unified_question(group_key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    primary = items[0]
    variant_labels = list(dict.fromkeys(str(i.get("label") or "").strip() for i in items if str(i.get("label") or "").strip()))
    company_names = list(dict.fromkeys(str(i.get("companyName") or "").strip() for i in items if str(i.get("companyName") or "").strip()))
    profile_key = next((i.get("suggestedProfileKey") for i in items if i.get("suggestedProfileKey")), None)
    normalized_key = (
        primary.get("suggestedNormalizedKey")
        or primary.get("normalizedKey")
        or (str(profile_key) if profile_key else normalize_field_key(variant_labels[0] if variant_labels else group_key))
    )
    canonical_id = group_key.replace(":", "_").replace(" ", "_")
    display_title = primary.get("displayTitle") or variant_labels[0] if variant_labels else "Question"
    display_context = str(primary.get("displayContext") or primary.get("storageHint") or "").strip()
    if len(company_names) > 1:
        display_context = " · ".join(
            p for p in [display_context, f"Asked on {len(company_names)} applications: {', '.join(company_names[:5])}{'…' if len(company_names) > 5 else ''}"] if p
        )
    unified = {
        "canonicalId": canonical_id,
        "fieldId": canonical_id,
        "label": variant_labels[0] if variant_labels else display_title,
        "displayTitle": display_title,
        "displayContext": display_context,
        "normalizedKey": normalized_key,
        "suggestedProfileKey": profile_key,
        "fieldType": primary.get("fieldType", "text"),
        "required": any(bool(i.get("required")) for i in items),
        "options": _merge_occurrence_options(items),
        "helpText": primary.get("helpText") or "",
        "section": primary.get("section") or "",
        "sensitivityCategory": primary.get("sensitivityCategory", "none"),
        "storageHint": primary.get("storageHint") or "",
        "wizardEligible": all(i.get("wizardEligible", True) for i in items),
        "variantLabels": variant_labels,
        "applicationCount": len({i.get("appId") for i in items}),
        "companyNames": company_names,
        "occurrenceCount": len(items),
        "targets": [
            {
                "appId": str(i.get("appId") or ""),
                "fieldId": str(i.get("fieldId") or ""),
                "normalizedKey": str(i.get("normalizedKey") or ""),
                "label": str(i.get("label") or ""),
                "companyName": str(i.get("companyName") or ""),
            }
            for i in items
        ],
    }
    unified["category"] = categorize_pending_field(unified)
    return unified


def _heuristic_dedupe_pending(occurrences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for occ in occurrences:
        profile_key = occ.get("suggestedProfileKey")
        if profile_key and profile_key in STANDARD_PROFILE_KEYS:
            group_key = f"profile:{profile_key}"
        else:
            group_key = str(
                occ.get("suggestedNormalizedKey")
                or occ.get("normalizedKey")
                or normalize_field_key(str(occ.get("label") or ""))
            )
        groups.setdefault(group_key, []).append(occ)

    unified = [_build_unified_question(key, items) for key, items in groups.items()]
    unified.sort(key=lambda q: (not q.get("required"), q.get("displayTitle", "")))
    return unified


def _occurrence_lookup(occurrences: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(o.get("fieldId") or ""): o for o in occurrences if o.get("fieldId")}


async def dedupe_pending_with_qwen(
    occurrences: list[dict[str, Any]],
    profile: dict[str, Any],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    """Cluster similar questions across applications into normalized canonical questions."""
    if not occurrences:
        return []

    client = create_llm_client(settings)
    if not client.enabled:
        return _heuristic_dedupe_pending(occurrences)

    profile_keys = _profile_keys_for_prompt(profile)
    payload = [
        {
            "fieldId": o.get("fieldId"),
            "appId": o.get("appId"),
            "companyName": o.get("companyName"),
            "label": o.get("label"),
            "displayTitle": o.get("displayTitle"),
            "helpText": o.get("helpText"),
            "section": o.get("section"),
            "fieldType": o.get("fieldType"),
            "suggestedProfileKey": o.get("suggestedProfileKey"),
            "normalizedKey": o.get("normalizedKey"),
            "options": (o.get("options") or [])[:8],
        }
        for o in occurrences
    ]
    prompt = (
        f"Normalize and deduplicate these {len(payload)} form fields from multiple job applications.\n"
        f"Available profile keys: {json.dumps(profile_keys)}\n\n"
        "Fields:\n"
        + json.dumps(payload, indent=2)
        + '\n\nReturn JSON: {"questions":[{"canonicalId":"...","displayTitle":"...","displayContext":"...",'
        '"wizardEligible":true,"profileKey":null,"normalizedKey":"...","sensitivityCategory":"...",'
        '"fieldIds":["..."],"variantLabels":["..."]}]}'
    )
    result = await client.complete(prompt, system=DEDUPE_SYSTEM, response_schema={"type": "object"})
    if not result.get("success"):
        return _heuristic_dedupe_pending(occurrences)

    by_field_id = _occurrence_lookup(occurrences)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    clusters = data.get("questions") or []
    used_ids: set[str] = set()
    unified: list[dict[str, Any]] = []

    for cluster in clusters:
        field_ids = [str(fid) for fid in cluster.get("fieldIds") or [] if str(fid)]
        items = [by_field_id[fid] for fid in field_ids if fid in by_field_id]
        if not items:
            continue
        used_ids.update(field_ids)
        group_key = str(cluster.get("canonicalId") or cluster.get("normalizedKey") or field_ids[0])
        built = _build_unified_question(group_key, items)
        if cluster.get("displayTitle"):
            built["displayTitle"] = str(cluster["displayTitle"]).strip()
        if cluster.get("displayContext") is not None:
            built["displayContext"] = str(cluster.get("displayContext") or "").strip()
        if cluster.get("profileKey") and str(cluster["profileKey"]) in STANDARD_PROFILE_KEYS:
            built["suggestedProfileKey"] = str(cluster["profileKey"])
        if cluster.get("normalizedKey"):
            built["normalizedKey"] = str(cluster["normalizedKey"])
        if cluster.get("sensitivityCategory"):
            built["sensitivityCategory"] = str(cluster["sensitivityCategory"])
        if "wizardEligible" in cluster:
            built["wizardEligible"] = bool(cluster["wizardEligible"])
        if cluster.get("variantLabels"):
            built["variantLabels"] = [str(v) for v in cluster["variantLabels"] if str(v).strip()]
        built["canonicalId"] = group_key
        built["fieldId"] = group_key
        built["category"] = categorize_pending_field(built)
        unified.append(built)

    leftover = [occ for occ in occurrences if str(occ.get("fieldId") or "") not in used_ids]
    if leftover:
        unified.extend(_heuristic_dedupe_pending(leftover))

    unified = [q for q in unified if q.get("wizardEligible", True)]
    unified.sort(key=lambda q: (not q.get("required"), q.get("displayTitle", "")))
    return unified


async def aggregate_pending_across_apps(
    db: Any,
    app_ids: list[str] | None = None,
    *,
    use_ai: bool = True,
) -> dict[str, Any]:
    """Collect pending fields from multiple applications; AI dedupe is opt-in."""
    drafts = list_application_drafts(db)
    if app_ids is not None:
        wanted = set(app_ids)
        drafts = [d for d in drafts if d.get("id") in wanted]

    profile = dict(get_kv(db, "profile") or {})
    settings = get_settings(db)
    occurrences: list[dict[str, Any]] = []
    applications: list[dict[str, Any]] = []

    for draft in drafts:
        app_id = str(draft.get("id") or "")
        if not app_id:
            continue
        if use_ai:
            readiness = await sync_application_readiness_async(db, app_id, persist=True)
        else:
            readiness = sync_application_readiness(db, app_id, persist=True)
        pending = list(readiness.get("pending") or [])
        if not pending:
            continue
        applications.append(
            {
                "appId": app_id,
                "companyName": draft.get("companyName", ""),
                "roleTitle": draft.get("roleTitle", ""),
                "pendingCount": len(pending),
                "readyForBrowser": readiness.get("readyForBrowser", False),
            }
        )
        for field in pending:
            occurrences.append(
                {
                    **field,
                    "appId": app_id,
                    "companyName": draft.get("companyName", ""),
                    "roleTitle": draft.get("roleTitle", ""),
                }
            )

    if not occurrences:
        return {
            "questions": [],
            "pending": [],
            "profilePending": [],
            "applicationPending": [],
            "profileKeysMissing": [],
            "count": 0,
            "rawOccurrenceCount": 0,
            "applicationCount": 0,
            "applicationIds": [],
            "applications": [],
            "readyForBrowser": True,
            "aiAnalyzed": use_ai,
        }

    if use_ai:
        enriched = await enrich_pending_with_qwen(occurrences, profile, settings)
        wizard_occurrences = filter_wizard_pending(enriched)
        unified = await dedupe_pending_with_qwen(wizard_occurrences, profile, settings)
    else:
        wizard_occurrences = filter_wizard_pending(occurrences)
        unified = _heuristic_dedupe_pending(wizard_occurrences)
    split = split_pending_fields(unified)

    return {
        "questions": unified,
        "pending": split["pending"],
        "profilePending": split["profilePending"],
        "applicationPending": split["applicationPending"],
        "profileKeysMissing": split["profileKeysMissing"],
        "count": len(unified),
        "rawOccurrenceCount": len(wizard_occurrences),
        "applicationCount": len(applications),
        "applicationIds": [a["appId"] for a in applications],
        "applications": applications,
        "readyForBrowser": len(unified) == 0,
        "aiAnalyzed": use_ai,
    }


async def save_unified_field_answers(
    db: Any,
    submissions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Save one normalized answer and fan it out to every matching application field."""
    affected_apps: set[str] = set()
    saved_targets = 0
    ready_apps: list[str] = []

    for submission in submissions:
        value = submission.get("value")
        if value is None or not str(value).strip():
            continue
        targets = submission.get("targets") or []
        profile_key = submission.get("profileKey") or None
        normalized_key = submission.get("normalizedKey") or None
        for target in targets:
            app_id = str(target.get("appId") or "")
            if not app_id:
                continue
            updated = save_field_answers(
                db,
                app_id,
                [
                    {
                        "fieldId": str(target.get("fieldId") or ""),
                        "normalizedKey": str(target.get("normalizedKey") or normalized_key or ""),
                        "profileKey": profile_key,
                        "value": str(value).strip(),
                    }
                ],
            )
            if updated:
                affected_apps.add(app_id)
                saved_targets += 1
                if updated.get("readyForBrowser"):
                    ready_apps.append(app_id)

    return {
        "affectedApplicationIds": sorted(affected_apps),
        "savedTargetCount": saved_targets,
        "readyApplicationIds": sorted(set(ready_apps)),
    }
