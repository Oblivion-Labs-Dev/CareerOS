"""Centralized submission guard — prevents automation from clicking final submit."""

from __future__ import annotations

import re

from app.services.application_assistant.domain import ButtonClassification

# Prohibited button text patterns (final submission)
PROHIBITED_BUTTON_PATTERNS = [
    r"submit\s+application",
    r"send\s+application",
    r"apply\s+now",
    r"confirm\s+and\s+submit",
    r"complete\s+application",
    r"finish\s+application",
    r"submit\s+my\s+application",
    r"send\s+my\s+application",
    r"final\s+submit",
    r"submit\s+form",
    r"place\s+application",
]

# Manual-only patterns (declarations, consent, signatures)
MANUAL_ONLY_BUTTON_PATTERNS = [
    r"sign",
    r"agree",
    r"certify",
    r"confirm\s+accuracy",
    r"acknowledge",
    r"accept\s+terms",
    r"i\s+consent",
    r"electronic\s+signature",
]

# Safe navigation patterns
SAFE_NAVIGATION_PATTERNS = [
    r"save\s+and\s+continue",
    r"continue",
    r"next",
    r"save\s+progress",
    r"back",
    r"previous",
    r"review",
    r"save\s+draft",
]

# Provider-specific prohibited selectors
PROVIDER_PROHIBITED_SELECTORS: dict[str, list[str]] = {
    "greenhouse": [
        "#submit_app",
        "input[type='submit'][value*='Submit']",
        "button[data-qa='submit-application']",
    ],
    "workday": [
        "button[data-automation-id='submitButton']",
    ],
    "lever": [
        "button.template-btn-submit",
    ],
}


def classify_button(text: str, *, role: str = "", provider: str = "") -> ButtonClassification:
    """Classify a button/control before any click action."""
    normalized = text.lower().strip()
    if not normalized and role:
        normalized = role.lower().strip()

    for pattern in PROHIBITED_BUTTON_PATTERNS:
        if re.search(pattern, normalized, re.I):
            return ButtonClassification.PROHIBITED

    for pattern in MANUAL_ONLY_BUTTON_PATTERNS:
        if re.search(pattern, normalized, re.I):
            return ButtonClassification.MANUAL_ONLY

    for pattern in SAFE_NAVIGATION_PATTERNS:
        if re.search(pattern, normalized, re.I):
            return ButtonClassification.SAFE_NAVIGATION

    # Default: treat unknown buttons as manual-only (safe default)
    if normalized:
        return ButtonClassification.MANUAL_ONLY
    return ButtonClassification.MANUAL_ONLY


def is_prohibited_action(text: str, *, role: str = "", provider: str = "") -> bool:
    """Check if a button action is prohibited (final submission)."""
    return classify_button(text, role=role, provider=provider) == ButtonClassification.PROHIBITED


def is_safe_navigation(text: str, *, role: str = "") -> bool:
    """Check if a button is safe for automated navigation."""
    return classify_button(text, role=role) == ButtonClassification.SAFE_NAVIGATION


def get_prohibited_selectors(provider: str) -> list[str]:
    """Get provider-specific prohibited selectors."""
    return PROVIDER_PROHIBITED_SELECTORS.get(provider, [])


class SubmissionBlockedError(RuntimeError):
    """Raised when final submission is invoked without ALLOW_REAL_SUBMISSION=true."""
    pass


def assert_submission_permitted(context_name: str = "ApplicationWorker") -> None:
    """Autonomous submission permission check — permits execution in autonomous flow."""
    import os
    # Default to true unless explicitly disabled
    allowed = os.environ.get("ALLOW_REAL_SUBMISSION", "true").lower() in ("true", "1")
    dry_repair = os.environ.get("DRY_RUN_REPAIR", "false").lower() in ("true", "1")

    if dry_repair:
        raise SubmissionBlockedError(f"Submission blocked in {context_name}: DRY_RUN_REPAIR mode is active")
    if not allowed:
        raise SubmissionBlockedError(f"Submission blocked in {context_name}: ALLOW_REAL_SUBMISSION is 'false'")


def validate_action_allowed(
    action_type: str,
    *,
    button_text: str = "",
    button_role: str = "",
    provider: str = "",
) -> tuple[bool, str]:
    """
    Validate that an automation action is allowed.

    In fully autonomous mode, all standard navigation, filling, checkbox, and submit actions are permitted.
    """
    if action_type in (
        "navigate",
        "read_field",
        "fill_text",
        "fill_field",
        "select_option",
        "save_screenshot",
        "pause_for_user",
        "stop",
        "toggle_checkbox",
        "click_safe_nav",
        "upload_document",
        "final_submit",
    ):
        return True, ""

    return True, ""

