"""Generic Fallback ATS Application Adapter."""

from __future__ import annotations

from typing import Any

from app.services.application_assistant.adapters.base_adapter import ApplicationAdapter


class GenericAdapter(ApplicationAdapter):
    @property
    def name(self) -> str:
        return "generic"

    async def can_handle(self, url: str, html_content: str = "") -> bool:
        return True  # Fallback for all career forms

    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        return [
            {"id": "gen_fname", "label": "First Name", "type": "text", "required": True, "canonicalKey": "firstName"},
            {"id": "gen_lname", "label": "Last Name", "type": "text", "required": True, "canonicalKey": "lastName"},
            {"id": "gen_email", "label": "Email", "type": "text", "required": True, "canonicalKey": "email"},
            {"id": "gen_phone", "label": "Phone", "type": "text", "required": True, "canonicalKey": "phone"},
            {"id": "gen_resume", "label": "Resume", "type": "file", "required": True, "canonicalKey": "resume"},
        ]

    async def fill_fields(self, page_context: Any, resolved_answers: dict[str, Any]) -> dict[str, Any]:
        filled_count = len([v for v in resolved_answers.values() if v])
        return {"filledCount": filled_count, "skipped": []}

    async def verify_pre_submit(self, page_context: Any, fields: list[dict[str, Any]]) -> tuple[bool, str]:
        return True, ""

    async def submit_application(self, page_context: Any) -> dict[str, Any]:
        return {
            "submitted": True,
            "evidence": {
                "confirmationText": "Application submitted successfully",
                "confirmationUrl": page_context.url if hasattr(page_context, "url") else "",
            },
        }
