"""Provider adapter base interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FormField:
    label: str
    normalized_key: str
    field_type: str
    required: bool = False
    options: list[str] = field(default_factory=list)
    help_text: str = ""
    section: str = ""
    selector_hint: str = ""
    name: str = ""
    id: str = ""


@dataclass
class JobListing:
    company: str
    title: str
    location: str = ""
    workplace_type: str = ""
    application_url: str = ""
    listing_url: str = ""
    external_job_id: str = ""
    description: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str = ""


@dataclass
class ProviderDetection:
    provider: str
    confidence: float
    supported: bool


class ProviderAdapter(ABC):
    """Base interface for ATS provider adapters."""

    name: str = "unknown"
    supported: bool = False

    @abstractmethod
    def detect(self, url: str, page_content: str = "") -> ProviderDetection:
        """Detect if this provider matches the given URL/page."""

    @abstractmethod
    async def discover_jobs(self, page: Any, options: dict[str, Any] | None = None) -> list[JobListing]:
        """Discover jobs from a careers page."""

    @abstractmethod
    async def extract_job(self, page: Any) -> JobListing | None:
        """Extract job details from a job listing page."""

    @abstractmethod
    async def inspect_application(self, page: Any) -> list[FormField]:
        """Inspect application form and return field definitions."""

    @abstractmethod
    def map_fields(self, fields: list[FormField], context: dict[str, Any]) -> list[dict[str, Any]]:
        """Map form fields to profile/answer-library data."""

    @abstractmethod
    async def fill_page(self, page: Any, approved_actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Fill form fields using approved actions only."""

    @abstractmethod
    async def get_progress(self, page: Any) -> dict[str, Any]:
        """Get current application progress."""

    @abstractmethod
    async def is_final_step(self, page: Any) -> bool:
        """Check if current page is the final submission step."""

    @abstractmethod
    async def detect_blocker(self, page: Any) -> dict[str, Any] | None:
        """Detect blockers (CAPTCHA, auth, etc.)."""

    @abstractmethod
    async def capture_state(self, page: Any) -> dict[str, Any]:
        """Capture current page state for persistence."""
