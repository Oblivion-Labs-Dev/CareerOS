"""Level 2 Adaptive Browser Recovery — uses Qwen to inspect DOM / accessibility tree / screenshots and return structured UI recovery actions."""

from __future__ import annotations

import json
from typing import Any

from app.services.application_assistant.failure_taxonomy import FailureContext, FailureType
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import get_settings, session_scope

ADAPTIVE_RECOVERY_SCHEMA = {
    "type": "object",
    "properties": {
        "recoveryType": {"type": "string", "enum": ["RUNTIME_ACTION", "STAGE", "UNRESOLVED"]},
        "confidence": {"type": "number"},
        "explanation": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["click", "find_button_by_role", "fill_field", "wait_for_selector", "scroll", "dismiss_modal"]},
                    "role": {"type": "string"},
                    "name": {"type": "string"},
                    "selector": {"type": "string"},
                    "value": {"type": "string"},
                    "timeoutMs": {"type": "number"},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["recoveryType", "confidence", "actions"],
}

ADAPTIVE_RECOVERY_SYSTEM = """You are the CareerOS Adaptive Browser Recovery Agent.
Analyze browser automation failure evidence (DOM, screenshot description, failed selectors, step context).
Determine if structured runtime actions can bypass the issue (e.g. dismiss modal, click alternative button role, wait for loading spinner).

Rules:
1. Do NOT suggest clicking final Submit or completing legal attestations.
2. If the page requires CAPTCHA, authentication, or unprovided information, return recoveryType: "STAGE".
3. Return valid JSON adhering to the schema.
"""


async def attempt_adaptive_browser_recovery(failure: FailureContext) -> dict[str, Any]:
    """Inspect failure context and query Qwen for structured UI recovery actions."""
    if failure.failure_type in (FailureType.CAPTCHA, FailureType.AUTH_REQUIRED, FailureType.UNSUPPORTED_QUESTION):
        return {
            "recoveryType": "STAGE",
            "confidence": 1.0,
            "explanation": f"Automated bypass strictly prohibited for {failure.failure_type.value}",
            "actions": [],
        }

    try:
        with session_scope() as db:
            settings = get_settings(db)
            client = create_llm_client(settings)

        if not client.enabled:
            return {"recoveryType": "UNRESOLVED", "confidence": 0.0, "explanation": "LLM client disabled", "actions": []}

        prompt = (
            f"Failure Type: {failure.failure_type.value}\n"
            f"ATS: {failure.ats_type} ({failure.adapter_name})\n"
            f"Current Step: {failure.current_step}\n"
            f"Error Message: {failure.error_message}\n"
            f"Failed Selectors: {failure.selector_attempts}\n"
            f"Last Action: {failure.last_successful_action}\n"
        )
        if failure.dom_snapshot_path:
            prompt += f"\nDOM Snapshot Path: {failure.dom_snapshot_path}\n"

        res = await client.complete(prompt, system=ADAPTIVE_RECOVERY_SYSTEM, response_schema=ADAPTIVE_RECOVERY_SCHEMA)
        if res.get("success") and isinstance(res.get("data"), dict):
            return res["data"]
    except Exception as exc:
        return {"recoveryType": "UNRESOLVED", "confidence": 0.0, "explanation": f"Adaptive recovery exception: {exc}", "actions": []}

    return {"recoveryType": "UNRESOLVED", "confidence": 0.0, "explanation": "Could not determine structured recovery actions", "actions": []}
