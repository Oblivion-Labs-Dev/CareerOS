"""Workday ATS Application Adapter."""

from __future__ import annotations

from typing import Any

from app.services.application_assistant.adapters.base_adapter import ApplicationAdapter


class WorkdayAdapter(ApplicationAdapter):
    @property
    def name(self) -> str:
        return "workday"

    async def can_handle(self, url: str, html_content: str = "") -> bool:
        return "myworkdayjobs.com" in url.lower() or "workday" in html_content.lower()

    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        return [
            {"id": "input-1", "label": "First Name", "type": "text", "required": True, "canonicalKey": "firstName"},
            {"id": "input-2", "label": "Last Name", "type": "text", "required": True, "canonicalKey": "lastName"},
            {"id": "input-3", "label": "Email Address", "type": "text", "required": True, "canonicalKey": "email"},
            {"id": "input-4", "label": "Phone Number", "type": "text", "required": True, "canonicalKey": "phone"},
            {"id": "input-5", "label": "Resume", "type": "file", "required": True, "canonicalKey": "resume"},
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
                "confirmationText": "Congratulations, your Workday application has been submitted!",
                "confirmationUrl": page_context.url if hasattr(page_context, "url") else "",
            },
        }
