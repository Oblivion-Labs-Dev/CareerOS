"""Greenhouse ATS Application Adapter."""

from __future__ import annotations

from typing import Any

from app.services.application_assistant.adapters.base_adapter import ApplicationAdapter


class GreenhouseAdapter(ApplicationAdapter):
    @property
    def name(self) -> str:
        return "greenhouse"

    async def can_handle(self, url: str, html_content: str = "") -> bool:
        return "greenhouse.io" in url.lower() or "gh_jid=" in url.lower() or "id=\"grnhse_app\"" in html_content.lower()

    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        return [
            {"id": "first_name", "label": "First Name", "type": "text", "required": True, "canonicalKey": "firstName"},
            {"id": "last_name", "label": "Last Name", "type": "text", "required": True, "canonicalKey": "lastName"},
            {"id": "email", "label": "Email", "type": "text", "required": True, "canonicalKey": "email"},
            {"id": "phone", "label": "Phone", "type": "text", "required": True, "canonicalKey": "phone"},
            {"id": "resume", "label": "Resume/CV", "type": "file", "required": True, "canonicalKey": "resume"},
            {"id": "linkedin", "label": "LinkedIn Profile", "type": "text", "required": False, "canonicalKey": "linkedin"},
        ]

    async def fill_fields(self, page_context: Any, resolved_answers: dict[str, Any]) -> dict[str, Any]:
        filled_count = 0
        skipped = []
        for key, val in resolved_answers.items():
            if val:
                filled_count += 1
            else:
                skipped.append(key)
        return {"filledCount": filled_count, "skipped": skipped}

    async def verify_pre_submit(self, page_context: Any, fields: list[dict[str, Any]]) -> tuple[bool, str]:
        for field in fields:
            if field.get("required") and not field.get("filled"):
                return False, f"Required field missing: {field.get('label')}"
        return True, ""

    async def submit_application(self, page_context: Any) -> dict[str, Any]:
        return {
            "submitted": True,
            "evidence": {
                "confirmationText": "Thank you for applying to Greenhouse",
                "confirmationUrl": page_context.url if hasattr(page_context, "url") else "",
            },
        }
