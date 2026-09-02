"""Qwen Pre-Submission Form Reviewer and Self-Healing Engine for CareerOS Autopilot."""

from __future__ import annotations

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

    # Rule-based fast check
    missing_required = []
    for f in form_state:
        label = f.get("label", "")
        val = f.get("value", "")
        is_required = f.get("required", False) or "*" in label
        
        if is_required and not val:
            missing_required.append({
                "fieldId": f.get("id") or "",
                "label": label,
                "issue": "Required field is empty",
                "suggestedFixValue": "",
                "actionType": "select_option" if f.get("isCombobox") else "type_text",
            })

    user_payload = {
        "company": company,
        "role": title,
        "candidateProfile": {
            "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}",
            "email": profile.get("email"),
            "phone": profile.get("phone"),
            "location": profile.get("location"),
            "workAuthorization": profile.get("workAuthorization", "Yes"),
            "sponsorship": profile.get("sponsorship", "Yes"),
            "veteran": profile.get("veteran", "I am not a protected veteran"),
            "disability": profile.get("disability", "No, I do not have a disability"),
            "gender": profile.get("gender", "Man"),
            "hispanic": profile.get("hispanic", "No"),
        },
        "formFields": form_state,
        "pageValidationErrors": validation_errors,
    }

    if llm:
        try:
            raw_res = await llm.generate_answer(
                prompt=f"Inspect this live application form state and verify if it is 100% ready for submission:\n{json.dumps(user_payload, indent=2)}",
                system_prompt=REVIEW_PROMPT_SYSTEM,
                temperature=0.1,
            )

            match = re.search(r"\{[\s\S]*\}", raw_res)
            if match:
                parsed = json.loads(match.group(0))
                return parsed

        except Exception as ex:
            logger.warning("Qwen review LLM call failed, using rule-based evaluation: %s", ex)

    # Fallback rule-based result
    is_ready = len(missing_required) == 0 and len(validation_errors) == 0
    return {
        "readyToSubmit": is_ready,
        "overallAssessment": "Rule-based form review check" if is_ready else f"Found {len(missing_required)} missing required fields",
        "missingOrInvalidFields": missing_required,
    }
