"""Fallback adapter for career sites with no dedicated implementation.

`can_handle` returns True for everything, so this is what `resolve_adapter`
returns for every employer-hosted careers page. That makes it the most dangerous
place in the package to fake a result: a stub that answered "submitted" here
would fabricate a submission for *every* unrecognised site.

It therefore reports honestly that it cannot drive the page. Filling an unknown
form is the `playwright_autopilot_executor`'s job, not this adapter's.
"""

from __future__ import annotations

from typing import Any

from app.services.application_assistant.adapters.base_adapter import (
    AdapterNotImplementedError,
    ApplicationAdapter,
)


class GenericAdapter(ApplicationAdapter):
    @property
    def name(self) -> str:
        return "generic"

    async def can_handle(self, url: str, html_content: str = "") -> bool:
        return True  # Fallback for all career forms

    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        raise AdapterNotImplementedError(
            "No dedicated adapter for this site; its form shape is unknown."
        )

    async def fill_fields(self, page_context: Any, resolved_answers: dict[str, Any]) -> dict[str, Any]:
        raise AdapterNotImplementedError("Generic form filling is not implemented.")

    async def verify_pre_submit(self, page_context: Any, fields: list[dict[str, Any]]) -> tuple[bool, str]:
        return False, "No dedicated adapter for this site."

    async def submit_application(self, page_context: Any) -> dict[str, Any]:
        raise AdapterNotImplementedError("Generic submission is not implemented.")
