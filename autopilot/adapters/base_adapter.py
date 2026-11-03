"""Abstract ApplicationAdapter interface for ATS forms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AdapterNotImplementedError(NotImplementedError):
    """An adapter recognises the site but cannot drive its form.

    Raised instead of returning a made-up result. The contract below promises
    that `submit_application` performs a real click and captures real
    confirmation evidence; an implementation that cannot do that must say so
    rather than satisfy the type signature with an invented success, which would
    record a job as SUBMITTED when no application was ever sent.
    """


class ApplicationAdapter(ABC):
    """Adapter interface for handling ATS form inspection, filling, and submission."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the ATS provider (e.g. greenhouse, lever, ashby, workday, generic)."""
        pass

    @abstractmethod
    async def can_handle(self, url: str, html_content: str = "") -> bool:
        """Check if this adapter can process the given job application page."""
        pass

    @abstractmethod
    async def inspect_fields(self, url: str, html_content: str = "") -> list[dict[str, Any]]:
        """Inspect the page and extract all fillable fields and question prompts."""
        pass

    @abstractmethod
    async def fill_fields(self, page_context: Any, resolved_answers: dict[str, Any]) -> dict[str, Any]:
        """Fill all supported fields on the Playwright page using resolved answers."""
        pass

    @abstractmethod
    async def verify_pre_submit(self, page_context: Any, fields: list[dict[str, Any]]) -> tuple[bool, str]:
        """Deterministic pre-submit check: required fields, resume attached, validation errors."""
        pass

    @abstractmethod
    async def submit_application(self, page_context: Any) -> dict[str, Any]:
        """Perform the submission click and capture confirmation evidence."""
        pass
