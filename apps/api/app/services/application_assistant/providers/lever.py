"""Lever ATS provider adapter — placeholder, not yet supported."""

from __future__ import annotations

import re
from typing import Any

from app.services.application_assistant.providers.base import (
    FormField,
    JobListing,
    ProviderAdapter,
    ProviderDetection,
)


class LeverAdapter(ProviderAdapter):
    name = "lever"
    supported = False

    def detect(self, url: str, page_content: str = "") -> ProviderDetection:
        text = f"{url} {page_content}".lower()
        if re.search(r"jobs\.lever\.co|lever\.co/", text):
            return ProviderDetection(provider=self.name, confidence=0.9, supported=False)
        return ProviderDetection(provider="unknown", confidence=0.0, supported=False)

    async def discover_jobs(self, page: Any, options: dict[str, Any] | None = None) -> list[JobListing]:
        raise NotImplementedError("Lever adapter is not yet supported")

    async def extract_job(self, page: Any) -> JobListing | None:
        raise NotImplementedError("Lever adapter is not yet supported")

    async def inspect_application(self, page: Any) -> list[FormField]:
        raise NotImplementedError("Lever adapter is not yet supported")

    def map_fields(self, fields: list[FormField], context: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError("Lever adapter is not yet supported")

    async def fill_page(self, page: Any, approved_actions: list[dict[str, Any]]) -> dict[str, Any]:
        raise NotImplementedError("Lever adapter is not yet supported")

    async def get_progress(self, page: Any) -> dict[str, Any]:
        raise NotImplementedError("Lever adapter is not yet supported")

    async def is_final_step(self, page: Any) -> bool:
        return True

    async def detect_blocker(self, page: Any) -> dict[str, Any] | None:
        return {"type": "unsupported_provider", "message": "Lever is not yet supported"}

    async def capture_state(self, page: Any) -> dict[str, Any]:
        return {"url": page.url, "fields": [], "progress": {}}
