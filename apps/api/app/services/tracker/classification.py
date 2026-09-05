"""Classify recruiter email threads into a fixed tag taxonomy (Tsenta-style inbox tagging).

Rule-based first (ordered keyword rules, same pattern as bounce_classifier.py), with an
optional OpenRouter LLM fallback only when no rule matches confidently and an API key is
configured. Deterministic and free by default.
"""

from __future__ import annotations

from typing import Any

# Ordered: first match wins. More specific / higher-signal categories go first so an
# offer email that also happens to mention "interview" still lands in Offer, etc.
CATEGORY_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "offer",
        "Offer",
        (
            "pleased to offer",
            "excited to extend",
            "job offer",
            "offer letter",
            "extend an offer",
            "extend you an offer",
            "compensation package",
            "we'd like to offer",
            "formal offer",
        ),
    ),
    (
        "rejection",
        "Rejection",
        (
            "unfortunately",
            "not moving forward",
            "other candidates",
            "decided not to proceed",
            "will not be moving forward",
            "not be moving forward",
            "not selected",
            "pursue other candidates",
            "position has been filled",
            "moving forward with other",
            "not the right fit at this time",
        ),
    ),
    (
        "assessment",
        "Assessment",
        (
            "coding challenge",
            "take-home",
            "take home assignment",
            "online assessment",
            "hackerrank",
            "codesignal",
            "technical screen",
            "complete the assessment",
            "coding exercise",
        ),
    ),
    (
        "interview",
        "Interview",
        (
            "schedule a call",
            "schedule an interview",
            "phone screen",
            "meet with the team",
            "would like to speak with you",
            "book a time",
            "interview invitation",
            "next round",
            "onsite interview",
            "virtual interview",
        ),
    ),
    (
        "verification",
        "Verification",
        (
            "confirm your email",
            "verify your email",
            "verification code",
            "security code",
            "security code for",
            "please verify",
            "one-time code",
            "one-time passcode",
            "enter the 8-character code",
            " otp ",
            "confirm your application",
        ),
    ),
    (
        "reminder",
        "Reminder",
        (
            "reminder",
            "following up on",
            "don't forget",
            "just checking in",
            "gentle reminder",
            "friendly reminder",
        ),
    ),
    (
        "applied",
        "Applied",
        (
            "thank you for applying",
            "application received",
            "we have received your application",
            "successfully submitted",
            "thanks for your interest in",
            "application has been received",
        ),
    ),
]

CATEGORY_LABELS: dict[str, str] = {key: label for key, label, _ in CATEGORY_RULES}
CATEGORY_LABELS["uncategorized"] = "Uncategorized"

LLM_SYSTEM_INSTRUCTION = (
    "You classify a single recruiter/ATS email into exactly one label from this fixed list: "
    "offer, rejection, assessment, interview, verification, reminder, applied, uncategorized. "
    'Respond with strict JSON: {"category": "<one of the labels above>", "confidence": <0-1 float>}. '
    "Use uncategorized only if truly none of the other labels fit."
)


def classify_text(subject: str = "", snippet: str = "", body: str = "") -> tuple[str, str, float]:
    """Return (category_key, label, confidence) for the given email text. Rule-based only."""
    subject_lower = (subject or "").lower()
    rest_lower = f"{snippet}\n{body}".lower()
    for key, label, tokens in CATEGORY_RULES:
        if any(token in subject_lower for token in tokens):
            return key, label, 0.9
    for key, label, tokens in CATEGORY_RULES:
        if any(token in rest_lower for token in tokens):
            return key, label, 0.75
    return "uncategorized", CATEGORY_LABELS["uncategorized"], 0.0


async def classify_text_with_llm_fallback(
    subject: str = "", snippet: str = "", body: str = ""
) -> tuple[str, str, float]:
    """Rule-based classification; falls back to an LLM call only when uncategorized and a
    key is configured. Never raises — any LLM failure just keeps the rule-based result."""
    category, label, confidence = classify_text(subject=subject, snippet=snippet, body=body)
    if category != "uncategorized":
        return category, label, confidence

    text = f"Subject: {subject}\n\n{snippet or body}".strip()
    if not text:
        return category, label, confidence

    try:
        from app.services.llm import call_openrouter_json

        result = await call_openrouter_json(
            f"Classify this recruiter email:\n\n{text[:1500]}",
            LLM_SYSTEM_INSTRUCTION,
            task="email_classification",
        )
    except Exception:
        return category, label, confidence

    if not result:
        return category, label, confidence

    llm_category = str(result.get("category") or "").strip().lower()
    if llm_category in CATEGORY_LABELS and llm_category != "uncategorized":
        try:
            llm_confidence = float(result.get("confidence", 0.6))
        except (TypeError, ValueError):
            llm_confidence = 0.6
        return llm_category, CATEGORY_LABELS[llm_category], max(0.0, min(1.0, llm_confidence))

    return category, label, confidence


def classify_thread(thread: dict[str, Any]) -> dict[str, Any]:
    """Sync, rule-based-only classification of one thread dict (from GmailImapClient)."""
    category, label, confidence = classify_text(
        subject=str(thread.get("subject") or ""),
        snippet=str(thread.get("snippet") or ""),
    )
    return {**thread, "category": category, "categoryLabel": label, "confidence": confidence}


async def classify_thread_async(thread: dict[str, Any]) -> dict[str, Any]:
    """Async classification with optional LLM fallback for ambiguous threads."""
    category, label, confidence = await classify_text_with_llm_fallback(
        subject=str(thread.get("subject") or ""),
        snippet=str(thread.get("snippet") or ""),
    )
    return {**thread, "category": category, "categoryLabel": label, "confidence": confidence}
