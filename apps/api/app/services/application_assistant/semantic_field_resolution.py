"""AI semantic matching for form fields Playwright/regex cannot interpret."""

from __future__ import annotations

import json
from typing import Any

from app.services.application_assistant.answer_classification import (
    AnswerClassification,
    normalize_field_key,
)
from app.services.application_assistant.canonical_registry import (
    CANONICAL_KEYS,
    CANONICAL_TO_PROFILE,
    CUSTOM_PREFIX,
    PROFILE_TO_CANONICAL,
    SPECIAL_CANONICAL_KEYS,
    approved_custom_keys,
    canonical_to_value_ref,
    is_valid_canonical_key,
    mapping_confidence_tier,
    registry_context_for_prompt,
    resolve_value_ref,
)
from app.services.application_assistant.llm_client import create_mapping_client

SEMANTIC_MATCH_SYSTEM = """You interpret employer job application form fields and match them to stored CareerOS answers.

Playwright and exact string matching fail when employers use different wording for the same question.
Examples of semantic equivalence:
- "Gender" = "What gender do you identify as?" = "Gender identity"
- "Why do you want to work here?" = "What excites you about joining our team?"
- "Are you authorized to work in the US?" = "Legally eligible to work in the United States"

Your task: for each form field, decide if it asks the same thing as a stored profile field or saved answer.
Match by meaning, not exact text.

Return JSON only:
{
  "matches": [
    {
      "fieldId": "<same id from input>",
      "matchType": "profile" | "answer_library" | "none",
      "canonicalKey": "<registry key e.g. demographics.gender or custom.why_reddit, or null>",
      "profileKey": "<standard profile key or null>",
      "normalizedKey": "<answer library snake_case key or null>",
      "confidence": 0.0,
      "reason": "<short explanation>",
      "learnedVariant": "<employer label if it should be saved as an alias>"
    }
  ]
}

Rules:
- matchType=none when no stored answer fits semantically
- Never invent answer values — only identify which stored question this field corresponds to
- confidence >= 0.85 for clear matches, 0.70-0.84 for plausible matches, below 0.70 → matchType none
- Use canonicalKey from the supplied registry when possible
- Different sensitive topics must NOT be merged (veteran ≠ disability ≠ gender)"""


def _field_needs_semantic_resolution(field: dict[str, Any]) -> bool:
    classification = field.get("classification", "unknown")
    if classification in (AnswerClassification.MANUAL_ONLY.value, AnswerClassification.VERIFIED.value):
        source = str(field.get("source") or field.get("mappedBy") or "")
        if classification == AnswerClassification.VERIFIED.value and (
            source.startswith("profile.")
            or source.startswith("answer_library.")
            or field.get("mappedBy") == "semantic"
        ):
            return False
    return classification in (
        AnswerClassification.UNKNOWN.value,
        AnswerClassification.INFERRED.value,
        AnswerClassification.CONFLICT.value,
    )


def _payload_for_semantic_match(field: dict[str, Any]) -> dict[str, Any]:
    return {
        "fieldId": field.get("fieldId"),
        "label": field.get("label"),
        "helpText": field.get("helpText") or field.get("help_text") or "",
        "section": field.get("section") or "",
        "fieldType": field.get("fieldType") or field.get("field_type") or "text",
        "options": (field.get("options") or [])[:10],
        "normalizedKey": field.get("normalizedKey"),
    }


def _apply_semantic_match(
    field: dict[str, Any],
    match: dict[str, Any],
    *,
    context: dict[str, Any],
    review_conf: float,
    auto_conf: float,
) -> bool:
    """Apply one semantic match onto a field. Returns True if field was resolved."""
    if str(match.get("matchType") or "none") == "none":
        return False

    confidence = float(match.get("confidence") or 0)
    tier = mapping_confidence_tier(confidence, auto=auto_conf, review=review_conf)
    if tier == "unknown":
        return False

    profile = context.get("profile") or {}
    answer_library = context.get("answerLibrary") or []
    documents = context.get("documents") or {}
    allow_inferred = bool(context.get("allowInferred"))
    custom_keys = approved_custom_keys(answer_library)

    canonical_key = str(match.get("canonicalKey") or "")
    if not canonical_key:
        profile_key = match.get("profileKey")
        if profile_key and profile_key in CANONICAL_TO_PROFILE.values():
            canonical_key = PROFILE_TO_CANONICAL.get(str(profile_key), "")
        norm_key = str(match.get("normalizedKey") or "")
        if not canonical_key and norm_key:
            canonical_key = f"{CUSTOM_PREFIX}{norm_key}"

    if not canonical_key or not is_valid_canonical_key(canonical_key, approved_custom_keys=custom_keys):
        return False

    value_ref = canonical_to_value_ref(canonical_key)
    if not value_ref:
        return False

    resolved = resolve_value_ref(
        value_ref,
        profile=profile,
        answer_library=answer_library,
        documents=documents,
        allow_inferred=allow_inferred,
    )
    if not resolved:
        return False

    classification, value, source = resolved
    requires_review = tier == "review"
    field.update(
        {
            "classification": classification if not requires_review else AnswerClassification.UNKNOWN.value,
            "proposedValue": value if not requires_review else None,
            "canonicalKey": canonical_key,
            "valueRef": value_ref,
            "confidence": confidence,
            "agentReason": str(match.get("reason") or "semantic_match"),
            "mappedBy": "semantic",
            "requiresUserReview": requires_review,
            "source": source,
            "semanticMatch": True,
        }
    )
    learned = str(match.get("learnedVariant") or field.get("label") or "").strip()
    if learned:
        field["learnedVariant"] = learned
    return not requires_review


async def resolve_unknown_fields_semantically(
    fields: list[dict[str, Any]],
    context: dict[str, Any],
    settings: dict[str, Any],
    *,
    review_conf: float = 0.70,
    auto_conf: float = 0.90,
    batch_size: int = 12,
    analyze_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use AI to match unknown fields to stored profile/answer-library entries by meaning."""
    from app.services.application_assistant.field_answers import _log_analyze

    report: dict[str, Any] = {"attempted": 0, "matched": [], "review": [], "skipped": []}
    ctx = analyze_context or {}
    app_id = str(ctx.get("applicationId") or "")
    company = str(ctx.get("companyName") or "")
    candidates = [f for f in fields if _field_needs_semantic_resolution(f)]
    if not candidates:
        return fields, report

    client = create_mapping_client(settings)
    if not client.enabled:
        report["skipped"].append("mapping_model_disabled")
        return fields, report

    answer_library = context.get("answerLibrary") or []
    registry = registry_context_for_prompt(answer_library)
    by_id = {str(f.get("fieldId") or ""): f for f in fields if f.get("fieldId")}
    matches_by_id: dict[str, dict[str, Any]] = {}
    total_batches = (len(candidates) + batch_size - 1) // batch_size

    for batch_num, start in enumerate(range(0, len(candidates), batch_size), start=1):
        batch = candidates[start : start + batch_size]
        report["attempted"] += len(batch)
        labels = [str(f.get("label") or "")[:50] for f in batch]
        _log_analyze(
            f"Semantic match batch {batch_num}/{total_batches}: {', '.join(labels[:3])}{'…' if len(labels) > 3 else ''}",
            event_type="analyze_llm",
            application_id=app_id or None,
            company_name=company,
            metadata={"batch": batch_num, "phase": "semantic_match"},
        )
        prompt = (
            "Match each employer form field to a stored profile field or saved answer by semantic meaning.\n"
            "Playwright cannot do this — only you can recognize paraphrased questions.\n\n"
            f"Registry:\n{json.dumps(registry, indent=2)[:12000]}\n\n"
            "Form fields:\n"
            + json.dumps([_payload_for_semantic_match(f) for f in batch], indent=2)
            + '\n\nReturn JSON: {"matches":[{"fieldId":"...","matchType":"...","canonicalKey":"...",'
            '"profileKey":null,"normalizedKey":"...","confidence":0.9,"reason":"...","learnedVariant":"..."}]}'
        )
        result = await client.complete(prompt, system=SEMANTIC_MATCH_SYSTEM, response_schema={"type": "object"})
        if not result.get("success"):
            report["skipped"].append(str(result.get("error", "semantic_match_failed")))
            _log_analyze(
                f"Semantic batch {batch_num} failed: {result.get('error', 'unknown')}",
                event_type="analyze_llm",
                application_id=app_id or None,
                company_name=company,
                success=False,
            )
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        batch_matches: list[str] = []
        for item in data.get("matches") or []:
            field_id = str(item.get("fieldId") or "")
            if field_id:
                matches_by_id[field_id] = item
                if str(item.get("matchType") or "none") != "none":
                    batch_matches.append(
                        f"{item.get('fieldId', '')}: {item.get('reason', 'matched')[:50]}"
                    )
        if batch_matches:
            _log_analyze(
                f"Semantic batch {batch_num}: {len(batch_matches)} match(es) — {'; '.join(batch_matches[:2])}",
                event_type="analyze_progress",
                application_id=app_id or None,
                company_name=company,
            )

    for field_id, match in matches_by_id.items():
        field = by_id.get(field_id)
        if not field:
            continue
        applied = _apply_semantic_match(
            field,
            match,
            context=context,
            review_conf=review_conf,
            auto_conf=auto_conf,
        )
        entry = {
            "fieldId": field_id,
            "label": field.get("label"),
            "canonicalKey": field.get("canonicalKey"),
            "confidence": match.get("confidence"),
        }
        if applied:
            report["matched"].append(entry)
        elif field.get("requiresUserReview"):
            report["review"].append(entry)

    return fields, report


def persist_learned_variants(
    db: Any,
    fields: list[dict[str, Any]],
    *,
    upsert_answer: Any,
    list_answer_library: Any,
) -> int:
    """Append employer labels the AI matched to answer-library questionVariants for future regex hits."""
    updated = 0
    library = list_answer_library(db)
    for field in fields:
        if not field.get("semanticMatch"):
            continue
        learned = str(field.get("learnedVariant") or field.get("label") or "").strip()
        canonical = str(field.get("canonicalKey") or "")
        if not learned or not canonical.startswith(CUSTOM_PREFIX):
            continue
        norm = canonical.removeprefix(CUSTOM_PREFIX)
        existing = next((e for e in library if e.get("normalizedKey") == norm), None)
        if not existing:
            continue
        variants = list(existing.get("questionVariants") or [])
        if learned not in variants:
            variants.append(learned)
            upsert_answer(db, {**existing, "questionVariants": variants})
            updated += 1
    return updated
