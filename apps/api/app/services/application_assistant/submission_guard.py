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


def validate_action_allowed(
    action_type: str,
    *,
    button_text: str = "",
    button_role: str = "",
    provider: str = "",
) -> tuple[bool, str]:
    """
    Validate that an automation action is allowed.

    Returns (allowed, reason).
    """
    if action_type in ("navigate", "read_field", "fill_text", "fill_field", "select_option", "save_screenshot", "pause_for_user", "stop"):
        return True, ""

    if action_type == "toggle_checkbox":
        classification = classify_button(button_text, role=button_role, provider=provider)
        if classification in (ButtonClassification.PROHIBITED, ButtonClassification.MANUAL_ONLY):
            return False, f"Checkbox classified as {classification.value}: {button_text}"
        return True, ""

    if action_type in ("click_safe_nav",):
        classification = classify_button(button_text, role=button_role, provider=provider)
        if classification == ButtonClassification.PROHIBITED:
            return False, f"Prohibited submission button detected: {button_text}"
        if classification == ButtonClassification.MANUAL_ONLY:
            return False, f"Manual-only control detected: {button_text}"
        if classification != ButtonClassification.SAFE_NAVIGATION:
            return False, f"Unknown button not classified as safe navigation: {button_text}"
        return True, ""

    if action_type == "upload_document":
        return True, ""

    return False, f"Unknown action type: {action_type}"
