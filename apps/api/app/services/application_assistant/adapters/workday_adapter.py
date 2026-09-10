"""Workday ATS Application Adapter.

Not implemented. Workday tenants require a per-employer candidate account and
drive their form through a multi-step wizard, none of which this adapter does.

It exists so `resolve_adapter` can name Workday as recognised-but-unsupported.
Every method that would otherwise have to claim work it did not do raises
instead: an adapter that reports a submission it never performed is worse than
no adapter at all, because the job is then recorded SUBMITTED with confirmation
evidence that was invented rather than observed.
"""

from __future__ import annotations

from typing import Any

from app.services.application_assistant.adapters.base_adapter import (
    AdapterNotImplementedError,
    ApplicationAdapter,
)


class WorkdayAdapter(ApplicationAdapter):
    @property
    def name(self) -> str:
        return "workday"

    async def can_handle(self, url: str, html_content: str = "") -> bool:
        return "myworkdayjobs.com" in url.lower() or "workday" in html_content.lower()

    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        raise AdapterNotImplementedError(
            "Workday applications are not automated: they require a candidate account "
            "on the employer's Workday tenant. Apply to this posting by hand."
        )

    async def fill_fields(self, page_context: Any, resolved_answers: dict[str, Any]) -> dict[str, Any]:
        raise AdapterNotImplementedError("Workday form filling is not implemented.")

    async def verify_pre_submit(self, page_context: Any, fields: list[dict[str, Any]]) -> tuple[bool, str]:
        return False, "Workday submissions are not automated."

    async def submit_application(self, page_context: Any) -> dict[str, Any]:
        raise AdapterNotImplementedError("Workday submission is not implemented.")
