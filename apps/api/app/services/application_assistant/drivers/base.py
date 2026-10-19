"""Extensible ATS application-driver registry — base types.

The application engine already ships as the autopilot stack (Greenhouse-centred
Playwright executor, submission policy/guard/receipts, human review gates).
This package adds the missing abstraction: per-platform *drivers* that declare
their capabilities explicitly, detect the ATS from a URL, load a job, discover
form questions, and deterministically map a candidate profile onto them —
without ever clicking a submit button.

Submission safety invariants (never weakened):
- Every driver in this registry is PREPARATION-ONLY.
  ``ApplicationDriverCapabilities.submit_authorized`` is False except for the
  Greenhouse legacy flow, and even there the only submission path remains the
  existing guarded autopilot runner (CAREEROS_LIVE_APPLY + approved job IDs +
  sequential runs + human review for unresolved answers). This package does
  not touch that path.
- Unfamiliar or ambiguous questions (salary expectations, sponsorship,
  eligibility, anything without a deterministic profile mapping or an approved
  answer) route to REVIEW — never guessed.
- CAPTCHA / MFA / assessment signals classify the application as MANUAL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApplicationMode(str, Enum):
    """Preparation outcome mode.

    AUTO here means "every required question had a deterministic mapping or an
    approved answer" — actual automatic submission stays behind the existing
    autopilot gates and is never triggered by drivers.
    """

    AUTO = "AUTO"
    REVIEW = "REVIEW"
    MANUAL = "MANUAL"


class QuestionType(str, Enum):
    TEXT = "text"
    EMAIL = "email"
    PHONE = "phone"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE = "file"
    DATE = "date"
    NUMBER = "number"
    UNKNOWN = "unknown"


@dataclass
class ApplicationDriverCapabilities:
    """What a driver can do. Every capability is explicit and declared."""

    detect_ats: bool = False
    load_job: bool = False
    discover_questions: bool = False
    map_profile: bool = False
    upload_resume: bool = False
    fill_fields: bool = True
    validate: bool = True
    submit_authorized: bool = False
    verify_submission: bool = False
    browser_fallback: bool = False

    def supported_operations(self) -> list[str]:
        ops = []
        if self.detect_ats:
            ops.append("detect_ats")
        if self.load_job:
            ops.append("load_job")
        if self.discover_questions:
            ops.append("discover_questions")
        if self.map_profile:
            ops.append("map_profile")
        if self.upload_resume:
            ops.append("upload_resume")
        if self.fill_fields:
            ops.append("fill_fields")
        if self.validate:
            ops.append("validate")
        if self.submit_authorized:
            ops.append("submit_authorized")
        if self.verify_submission:
            ops.append("verify_submission")
        if self.browser_fallback:
            ops.append("browser_fallback")
        return ops

    def unsupported_operations(self) -> list[str]:
        declared = [
            "detect_ats",
            "load_job",
            "discover_questions",
            "map_profile",
            "upload_resume",
            "fill_fields",
            "validate",
            "submit_authorized",
            "verify_submission",
            "browser_fallback",
        ]
        return [op for op in declared if op not in self.supported_operations()]


@dataclass
class FormQuestion:
    """A normalized form question discovered on an ATS apply page."""

    key: str
    label: str
    type: str = QuestionType.TEXT
    required: bool = False
    options: list[str] = field(default_factory=list)
    # Deterministic mapping result (never an invented answer):
    mapped_value: str | None = None
    mapping_source: str = "review_required"  # profile|approved_answer|review_required|manual
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "options": self.options,
            "mappedValue": self.mapped_value,
            "mappingSource": self.mapping_source,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class PreparedApplication:
    """Outcome of driver preparation. Contains plans only — never a submission."""

    platform: str
    job_url: str
    company: str
    title: str
    mode: ApplicationMode
    capabilities: ApplicationDriverCapabilities
    questions: list[FormQuestion] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    manual_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    form_question_count: int = 0

    @property
    def auto_mapped_count(self) -> int:
        return sum(
            1 for q in self.questions if q.mapping_source in ("profile", "approved_answer")
        )

    @property
    def review_count(self) -> int:
        return sum(1 for q in self.questions if q.mapping_source == "review_required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "jobUrl": self.job_url,
            "company": self.company,
            "title": self.title,
            "mode": self.mode.value,
            "capabilities": self.capabilities.supported_operations(),
            "unsupportedCapabilities": self.capabilities.unsupported_operations(),
            "questions": [q.to_dict() for q in self.questions],
            "autoMapped": self.auto_mapped_count,
            "reviewRequired": self.review_count,
            "reviewReasons": self.review_reasons,
            "manualReasons": self.manual_reasons,
            "warnings": self.warnings,
            "formQuestionCount": self.form_question_count,
            "submission": {
                "supported": self.capabilities.submit_authorized,
                "authorization": "NOT_REQUESTED",
            },
        }


class ApplicationDriver:
    """Base class for per-ATS application drivers.

    Subclasses declare ``platform`` and ``capabilities`` and may override
    ``detect`` and ``prepare``. The default ``prepare`` loads the apply page
    (fixture HTML, injected fetcher, or a permitted public GET), discovers
    questions with the generic deterministic form scanner, maps them from the
    candidate profile / approved answers, and classifies the outcome mode.
    """

    platform: str = "generic"
    display_name: str = "Generic"
    capabilities: ApplicationDriverCapabilities = ApplicationDriverCapabilities()
    url_host_patterns: tuple[str, ...] = ()

    def detect(self, url: str) -> bool:
        if not url:
            return False
        lowered = url.lower()
        return any(pattern in lowered for pattern in self.url_host_patterns)

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------

    def prepare(
        self,
        job: dict[str, Any],
        profile: dict[str, Any],
        *,
        form_html: str | None = None,
        fetch_form_html: Any = None,
        approved_answers: dict[str, str] | None = None,
    ) -> PreparedApplication:
        from .forms import scan_form_fields
        from .profile_map import map_questions

        apply_url = (
            job.get("applyUrl")
            or job.get("applicationUrl")
            or job.get("url")
            or job.get("canonicalUrl")
            or ""
        )
        prepared = PreparedApplication(
            platform=self.platform,
            job_url=apply_url,
            company=str(job.get("companyName") or job.get("company") or ""),
            title=str(job.get("title") or ""),
            mode=ApplicationMode.REVIEW,
            capabilities=self.capabilities,
        )
        if not self.capabilities.load_job:
            prepared.manual_reasons.append(
                f"{self.display_name} job loading is not supported by this driver"
            )
            prepared.mode = ApplicationMode.MANUAL
            return prepared
        if not apply_url:
            prepared.manual_reasons.append("No application URL on job record")
            prepared.mode = ApplicationMode.MANUAL
            return prepared

        html = form_html
        if html is None and fetch_form_html is not None:
            html = fetch_form_html(apply_url)
        raw_fields = scan_form_fields(html) if html else []
        prepared.form_question_count = len(raw_fields)
        if html is None:
            prepared.warnings.append(
                "Apply page HTML unavailable; questions not discovered (provide formHtml or fetcher)"
            )
        elif not raw_fields:
            prepared.warnings.append("No form fields found on apply page")

        mapped = map_questions(raw_fields, profile, approved_answers or {})
        prepared.questions = mapped.questions
        prepared.review_reasons = mapped.review_reasons
        prepared.manual_reasons.extend(mapped.manual_reasons)

        if mapped.manual_reasons:
            prepared.mode = ApplicationMode.MANUAL
        elif mapped.review_reasons:
            prepared.mode = ApplicationMode.REVIEW
        else:
            prepared.mode = ApplicationMode.AUTO
        return prepared
