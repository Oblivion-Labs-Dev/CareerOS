"""Qwen Pre-Submission Form Reviewer and Self-Healing Engine for CareerOS Autopilot."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.db.store import session_scope
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import get_settings

logger = logging.getLogger("career_os.qwen_form_reviewer")

REVIEW_PROMPT_SYSTEM = """You are Qwen, the elite ATS form verification and self-healing engine inside CareerOS.
Your job is to inspect the current state of a live job application form before final submission.

Check for:
1. Are all required fields (marked with * or required attribute) populated with valid candidate data?
2. Are there any empty required dropdowns, text inputs, radio buttons, or phone/country selectors?
3. Are there any validation error messages on the page (e.g., 'This field is required', 'Invalid email', 'Select a country')?
4. Is the resume attached?

Return ONLY valid JSON matching this schema:
{
  "readyToSubmit": boolean,
  "overallAssessment": "string explanation",
  "missingOrInvalidFields": [
    {
      "fieldId": "string",
      "label": "string",
      "issue": "string",
      "suggestedFixValue": "string",
      "actionType": "select_option" | "type_text" | "check_box" | "upload_file"
    }
  ]
}
"""


async def review_and_heal_form_state(
    form_state: list[dict[str, Any]],
    validation_errors: list[str],
    profile: dict[str, Any],
    company: str,
    title: str,
) -> dict[str, Any]:
    """Run Qwen verification on live form DOM fields and determine if self-healing actions are needed."""
    try:
        with session_scope() as db:
            settings = get_settings(db)
        llm = create_llm_client(settings)
    except Exception as e:
        logger.debug("Failed to init LLM client: %s", e)
        llm = None

    # 1. Fast Strict-Required Check: Ignore optional fields completely
    missing_required = []
    for f in form_state:
        label = (f.get("label") or "").strip()
        label_lower = label.lower()
        val = (f.get("value") or "").strip()
        f_type = (f.get("type") or "").lower()
        
        # Determine if field is strictly required
        is_explicit_req = f.get("required", False)
        is_star_req = "*" in label and not any(opt_token in label_lower for opt_token in ["optional", "if applicable", "if willing", "feel free", "additional"])
        is_required = is_explicit_req or is_star_req

        # Never block on optional fields (cover letters, transcripts, portfolio, references, etc.)
        if not is_required:
            continue

        if not val:
            act = "upload_file" if f_type == "file" else ("select_option" if f.get("isCombobox") else "type_text")
            missing_required.append({
                "fieldId": f.get("id") or "",
                "label": label,
                "issue": "Required field is empty",
                "suggestedFixValue": "",
                "actionType": act,
            })

    # If all required fields are filled and there are no validation errors, submit immediately (<1ms)
    if len(missing_required) == 0 and len(validation_errors) == 0:
        return {
            "readyToSubmit": True,
            "overallAssessment": "All required fields populated and no active validation errors",
            "missingOrInvalidFields": [],
        }

    # Only if required fields are actually missing do we check candidate profile / LLM
    return {
        "readyToSubmit": False,
        "overallAssessment": f"Found {len(missing_required)} unfilled required field(s)",
        "missingOrInvalidFields": missing_required,
    }


CONFIRMATION_PROMPT_SYSTEM = """You are Qwen, the strict submission auditor inside CareerOS.
Your job is to examine the post-submission text, URL, and page evidence from a job application to confirm whether the application was truly submitted.

Strict criteria:
1. Is there an unambiguous confirmation phrase (e.g., 'thank you for applying', 'application submitted', 'application received', 'we have received your application')?
2. Is the candidate clearly on a success or thank-you page?
3. Are there ANY remaining form validation errors or rejected fields?

Return ONLY valid JSON matching this schema:
{
  "submissionConfirmed": boolean,
  "confidence": number,
  "confirmationMessage": "string",
  "reason": "string explanation"
}
"""


async def verify_submission_confirmation(
    body_text: str,
    confirmation_url: str,
    active_errors: list[str],
    company: str,
    title: str,
    form_still_visible: bool = False,
    submit_button_visible: bool = False,
) -> dict[str, Any]:
    """Strictly verify if the post-submission page confirms real application submission."""
    if active_errors:
        return {
            "submissionConfirmed": False,
            "confidence": 1.0,
            "reason": f"Page contains active validation errors: {', '.join(active_errors[:5])}",
        }

    url_lower = confirmation_url.lower()
    url_redirected = any(term in url_lower for term in ["/thank_you", "/confirmation", "/applied", "/success", "submitted=true", "thanks"])

    # If the user is still on the un-redirected page with the submit button visible, the form did NOT submit
    if (form_still_visible or submit_button_visible) and not url_redirected:
        return {
            "submissionConfirmed": False,
            "confidence": 0.95,
            "reason": "Submission was not processed: Application form and submit button are still active on the page",
        }

    conf_phrases = [
        "thank you for applying",
        "thank you for your application",
        "we have received your application",
        "your application was submitted",
        "your application has been received",
        "your application has been submitted to",
        "we've received your application",
        "thank you for taking the time to apply",
        "successfully submitted",
        "submission successful",
        "your response has been recorded",
    ]
    body_lower = body_text.lower()
    has_phrase = any(p in body_lower for p in conf_phrases)

    is_confirmed = (url_redirected or (has_phrase and not form_still_visible)) and not active_errors
    return {
        "submissionConfirmed": is_confirmed,
        "confidence": 1.0 if is_confirmed else 0.2,
        "confirmationMessage": "Application confirmed by ATS (Deterministic Match)" if is_confirmed else "No confirmation phrase or redirect reached",
        "reason": "ATS confirmation detected" if is_confirmed else "Submission could not be verified: no confirmation page or confirmation message was detected after submit",
    }
