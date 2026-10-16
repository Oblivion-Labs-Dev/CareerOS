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

    def map_fields(self, fields: list[FormField], context: dict[str, Any]) -> list[dict[str, Any]]:
        """Map form fields to profile/answer-library data."""
        from app.services.application_assistant.answer_classification import classify_answer

        profile = context.get("profile", {})
        answer_library = context.get("answerLibrary", [])
        allow_inferred = context.get("allowInferred", False)

        mapped: list[dict[str, Any]] = []
        for f in fields:
            classification, value, confidence, source, sensitivity = classify_answer(
                label=f.label,
                help_text=f.help_text,
                field_type=f.field_type,
                profile=profile,
                answer_library=answer_library,
                allow_inferred=allow_inferred,
                name=f.name,
                field_id=f.id,
                selector_hint=f.selector_hint,
                options=f.options,
            )
            mapped.append({
                "label": f.label,
                "normalizedKey": f.normalized_key,
                "fieldType": f.field_type,
                "required": f.required,
                "options": f.options,
                "helpText": f.help_text,
                "section": f.section,
                "selectorHint": f.selector_hint,
                "name": f.name,
                "classification": classification.value,
                "proposedValue": value,
                "confidence": confidence,
                "source": source,
                "sensitivityCategory": sensitivity.value,
                "filled": False,
            })
        return mapped

    async def fill_page(
        self,
        page: Any,
        approved_actions: list[dict[str, Any]],
        *,
        profile: dict[str, Any] | None = None,
        fast_replay: bool = False,
    ) -> dict[str, Any]:
        """Fill form fields using approved actions only."""
        if fast_replay:
            from app.services.application_assistant.field_fill_engine import fill_page_fast_replay
            return await fill_page_fast_replay(page, approved_actions, profile=profile)

        from app.services.application_assistant.field_fill_engine import fill_field
        from app.services.application_assistant.submission_guard import (
            is_prohibited_action,
            validate_action_allowed,
        )

        results = {"filled": [], "skipped": [], "errors": []}
        for action in approved_actions:
            action_type = action.get("type", "")
            allowed, reason = validate_action_allowed(
                action_type,
                button_text=action.get("buttonText", ""),
                provider=self.name,
            )
            if not allowed:
                results["skipped"].append({"action": action, "reason": reason})
                continue

            try:
                if action_type in ("fill_text", "fill_field", "select_option", "upload_document"):
                    val = action.get("filePath", "") if action_type == "upload_document" else action.get("value", "")
                    ok, fill_reason = await fill_field(page, action, val, profile=profile)
                    if ok:
                        results["filled"].append(action)
                    else:
                        results["skipped"].append({"action": action, "reason": fill_reason})
                elif action_type == "click_safe_nav":
                    text = action.get("buttonText", "")
                    if is_prohibited_action(text, provider=self.name):
                        results["skipped"].append({"action": action, "reason": "Prohibited submit button"})
                        continue
                    btn = None
                    if hasattr(page, "get_by_role") and text:
                        role_btn = page.get_by_role("button", name=text).first
                        if await role_btn.count() > 0:
                            btn = role_btn
                    if not btn and action.get("selectorHint"):
                        btn = await page.query_selector(action.get("selectorHint", ""))
                    if btn:
                        await btn.click()
                        await page.wait_for_timeout(1000)
                        results["filled"].append(action)
            except Exception as exc:
                results["errors"].append({"action": action, "error": str(exc)})

        return results


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
