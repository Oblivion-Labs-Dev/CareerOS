#!/usr/bin/env python3
"""Classify Gmail bounce messages into actionable delivery-failure categories."""

from __future__ import annotations

from typing import Any

# Ordered: first match wins (more specific first).
BOUNCE_CATEGORY_RULES: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "invalid_address",
        "Invalid address",
        (
            "address not found",
            "user unknown",
            "5.1.1",
            "does not exist",
            "no such user",
            "unknown user",
            "invalid recipient",
            "recipient address rejected",
            "no mailbox here",
            "mailbox not found",
            "user not found",
        ),
    ),
    (
        "mailbox_full",
        "Mailbox full",
        ("mailbox full", "over quota", "quota exceeded", "5.2.2", "insufficient system storage"),
    ),
    (
        "mailbox_unavailable",
        "Mailbox unavailable",
        (
            "mailbox unavailable",
            "mailbox disabled",
            "account disabled",
            "account is disabled",
            "user is over quota",
            "recipient inbox full",
        ),
    ),
    (
        "message_blocked",
        "Message blocked",
        (
            "message blocked",
            "blocked by",
            "550 5.7",
            "5.7.1",
            "policy rejection",
            "rejected for policy",
            "not accepted",
        ),
    ),
    (
        "spam_or_reputation",
        "Spam / reputation",
        ("spam", "reputation", "blacklist", "block list", "denied by policy"),
    ),
    (
        "relay_rejected",
        "Relay rejected",
        ("relay access denied", "relaying denied", "unable to relay"),
    ),
    (
        "temporary_failure",
        "Temporary failure",
        ("try again later", "temporary", "4.2.", "421 ", "451 ", "deferred", "greylist", "try again"),
    ),
    (
        "not_delivered",
        "Mail not delivered",
        (
            "wasn't delivered",
            "was not delivered",
            "could not be delivered",
            "undeliverable",
            "delivery incomplete",
            "delivery has failed",
            "mail delivery failed",
            "delivery failure",
        ),
    ),
]

CATEGORY_LABELS = {key: label for key, label, _ in BOUNCE_CATEGORY_RULES}
CATEGORY_LABELS["other"] = "Other bounce"
CATEGORY_LABELS["send_failed"] = "Send failed"
CATEGORY_LABELS["pending"] = "Pending"
CATEGORY_LABELS["delivered"] = "Delivered"


def classify_bounce_text(subject: str = "", snippet: str = "", body: str = "") -> tuple[str, str]:
    """Return (category_key, human_label) for bounce text."""
    text = f"{subject}\n{snippet}\n{body}".lower()
    for key, label, tokens in BOUNCE_CATEGORY_RULES:
        if any(token in text for token in tokens):
            return key, label
    return "other", CATEGORY_LABELS["other"]


def extract_error_reason(subject: str = "", snippet: str = "") -> str:
    """Pick a short human-readable error line from bounce subject/snippet."""
    cleaned_subject = " ".join((subject or "").replace("\r", " ").replace("\n", " ").split())
    cleaned_snippet = " ".join((snippet or "").replace("\r", " ").replace("\n", " ").split())

    for marker in (
        "Address not found",
        "Mailbox unavailable",
        "Mailbox full",
        "Message blocked",
        "Delivery incomplete",
        "Mail Delivery Failed",
    ):
        if marker.lower() in cleaned_snippet.lower() or marker.lower() in cleaned_subject.lower():
            # Prefer the bold/error lead-in from Gmail DSN snippets.
            idx = cleaned_snippet.lower().find(marker.lower())
            if idx >= 0:
                return cleaned_snippet[idx : idx + 140].strip()
            return marker

    if cleaned_snippet:
        # Drop leading decorative stars from Gmail HTML-to-text snippets.
        snippet = cleaned_snippet.lstrip("* ").strip()
        return snippet[:160]
    if cleaned_subject:
        return cleaned_subject[:160]
    return "Delivery failed"


def classify_bounce_message(message: dict[str, Any]) -> dict[str, str]:
    subject = str(message.get("subject") or "")
    snippet = str(message.get("snippet") or "")
    category, label = classify_bounce_text(subject=subject, snippet=snippet)
    reason = extract_error_reason(subject=subject, snippet=snippet)
    return {
        "bounceCategory": category,
        "bounceCategoryLabel": label,
        "bounceReason": reason,
    }


def enrich_invalid_email_records(
    invalid_emails: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach the best bounce category/reason onto each invalid email record."""
    by_email: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        classified = classify_bounce_message(message)
        for address in message.get("failedEmails") or []:
            email = str(address).lower()
            by_email.setdefault(email, []).append(
                {
                    **classified,
                    "date": message.get("date"),
                    "snippet": message.get("snippet"),
                    "subject": message.get("subject"),
                }
            )

    enriched: list[dict[str, Any]] = []
    for item in invalid_emails:
        email = str(item.get("email") or "").lower()
        record = dict(item)
        hits = by_email.get(email) or []
        if hits:
            # Prefer invalid_address / specific categories over generic; then latest date.
            priority = {
                "invalid_address": 0,
                "mailbox_full": 1,
                "mailbox_unavailable": 2,
                "message_blocked": 3,
                "spam_or_reputation": 4,
                "relay_rejected": 5,
                "temporary_failure": 6,
                "not_delivered": 7,
                "other": 8,
            }
            hits_sorted = sorted(
                hits,
                key=lambda hit: (
                    priority.get(str(hit.get("bounceCategory")), 99),
                    str(hit.get("date") or ""),
                ),
            )
            best = hits_sorted[0]
            record["bounceCategory"] = best["bounceCategory"]
            record["bounceCategoryLabel"] = best["bounceCategoryLabel"]
            record["bounceReason"] = best["bounceReason"]
        else:
            # Restored-from-cleaned-list records without the original DSN message.
            record.setdefault("bounceCategory", "invalid_address")
            record.setdefault("bounceCategoryLabel", CATEGORY_LABELS["invalid_address"])
            record.setdefault("bounceReason", "Address not found (restored from prior bounce cleanup)")
        enriched.append(record)
    return enriched
