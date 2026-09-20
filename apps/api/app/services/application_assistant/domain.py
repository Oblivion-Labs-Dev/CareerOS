"""Core domain types for the Application Assistant."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    GREENHOUSE = "greenhouse"
    WORKDAY = "workday"
    LEVER = "lever"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class AnswerClassification(str, Enum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    MANUAL_ONLY = "manual_only"


class ApplicationStatus(str, Enum):
    READY_TO_PREPARE = "ready_to_prepare"
    IN_PROGRESS = "in_progress"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"
    READY_FOR_FINAL_REVIEW = "ready_for_final_review"
    SUBMITTED_MANUALLY = "submitted_manually"
    ARCHIVED = "archived"


class DiscoveryRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AutopilotRunStatus(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    RECOVERING = "RECOVERING"
    FAILED = "FAILED"


class AutopilotJobStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    SCORED = "SCORED"
    QUEUED = "QUEUED"
    APPLYING = "APPLYING"
    STAGED = "STAGED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    # The posting is live and worth applying to, but automation will never
    # complete it — a CAPTCHA guards the board, or its form cannot be driven.
    # Distinct from NEEDS_REVIEW, where answering a question lets Autopilot
    # carry on, and from INELIGIBLE, which means there is nothing to apply to.
    # The candidate can still open these and submit them by hand, so they are
    # real opportunities and must stay visible.
    MANUAL_REVIEW = "MANUAL_REVIEW"
    SUBMITTED = "SUBMITTED"
    # The attempt reached the final submit and then lost the thread — the click
    # landed but no confirmation could be read, the browser died mid-verify, the
    # process was killed. The application may or may not have been sent.
    #
    # This exists because the alternative was recording it as FAILED, and FAILED
    # is a retryable bucket: the requeue endpoints and the in-run retry both put
    # it straight back on the queue, which applies a second time to a posting
    # that may already have the candidate's application. Automation must never
    # retry one of these on its own. The user opens the posting, checks whether
    # their application is there, and records the answer with the state selector;
    # a confirmation email reconciles it forward to SUBMITTED without their help.
    SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
    # A SUBMITTED application the employer has since declined. Split out from
    # SUBMITTED so "still open" (awaiting a response) can be counted as
    # SUBMITTED minus REJECTED, rather than everything that was ever sent.
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    # Terminal and non-actionable: the candidate cannot apply to this posting at
    # all, so it must never sit in the review or retry queues alongside work the
    # user can actually resolve. Distinct from SKIPPED (a soft filter that may
    # pass later, e.g. after a profile change) and from FAILED (an automation
    # problem worth retrying). Always paired with an IneligibilityReason.
    INELIGIBLE = "INELIGIBLE"


class IneligibilityReason(str, Enum):
    """Why a posting is permanently closed to this candidate.

    Kept separate from ApplicationErrorType: those describe something going wrong
    with the automation, these describe the posting itself being a dead end.
    """

    REQUIRES_US_CITIZENSHIP = "REQUIRES_US_CITIZENSHIP"
    NO_VISA_SPONSORSHIP = "NO_VISA_SPONSORSHIP"
    OUTSIDE_UNITED_STATES = "OUTSIDE_UNITED_STATES"
    POSTING_EXPIRED = "POSTING_EXPIRED"
    NOT_A_REAL_POSTING = "NOT_A_REAL_POSTING"
    DUPLICATE_APPLICATION = "DUPLICATE_APPLICATION"
    # The board itself blocks automation (CAPTCHA, Turnstile, bot detection).
    # Nothing about the candidate or a retry changes this.
    BOT_PROTECTED_BOARD = "BOT_PROTECTED_BOARD"
    # The form demands a fact the profile genuinely does not hold (a GPA, a
    # specific unverifiable experience claim). Permanent until the candidate
    # supplies it — and never something to invent.
    REQUIRES_UNAVAILABLE_INFORMATION = "REQUIRES_UNAVAILABLE_INFORMATION"
    # A Tier-1 target company. Nothing is wrong with the posting or the
    # candidate — the operator has reserved these for a hand-written
    # application, so the batch declines to submit on their behalf.
    MANUAL_APPLICATION_REQUIRED = "MANUAL_APPLICATION_REQUIRED"
    ROLE_EXCLUDED = "ROLE_EXCLUDED"
    COMPANY_CAP_REACHED = "COMPANY_CAP_REACHED"
    # The candidate's own standing decision, recorded in Settings — not
    # something the automation discovered about the posting. Permanent until
    # the candidate removes the company from their list.
    COMPANY_BLACKLISTED = "COMPANY_BLACKLISTED"


class ApplicationErrorType(str, Enum):
    NAVIGATION_TIMEOUT = "NAVIGATION_TIMEOUT"
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    PAGE_CHANGED = "PAGE_CHANGED"
    NETWORK_ERROR = "NETWORK_ERROR"
    BROWSER_CRASH = "BROWSER_CRASH"
    AI_ERROR = "AI_ERROR"
    AI_TIMEOUT = "AI_TIMEOUT"
    UNSUPPORTED_QUESTION = "UNSUPPORTED_QUESTION"
    UNSUPPORTED_ATS = "UNSUPPORTED_ATS"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CAPTCHA = "CAPTCHA"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UPLOAD_ERROR = "UPLOAD_ERROR"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    JOB_CLOSED = "JOB_CLOSED"
    DUPLICATE_APPLICATION = "DUPLICATE_APPLICATION"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class CheckpointStep(str, Enum):
    JOB_CLAIMED = "JOB_CLAIMED"
    PAGE_OPENED = "PAGE_OPENED"
    FORM_DISCOVERED = "FORM_DISCOVERED"
    RESUME_UPLOADED = "RESUME_UPLOADED"
    PROFILE_FIELDS_FILLED = "PROFILE_FIELDS_FILLED"
    QUESTIONS_COMPLETED = "QUESTIONS_COMPLETED"
    PRE_SUBMISSION_CHECK = "PRE_SUBMISSION_CHECK"
    SUBMITTING = "SUBMITTING"
    VERIFYING_SUBMISSION = "VERIFYING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    STAGED = "STAGED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class AnswerType(str, Enum):
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    BOOLEAN = "boolean"
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    DATE = "date"
    NUMBER = "number"
    URL = "url"
    FILE_REFERENCE = "file_reference"


class SensitivityCategory(str, Enum):
    NONE = "none"
    WORK_AUTHORIZATION = "work_authorization"
    IMMIGRATION = "immigration"
    DISABILITY = "disability"
    VETERAN = "veteran"
    DEMOGRAPHIC = "demographic"
    CRIMINAL = "criminal"
    CLEARANCE = "clearance"
    SALARY = "salary"
    CONSENT = "consent"
    DECLARATION = "declaration"
    SIGNATURE = "signature"


class ErrorCategory(str, Enum):
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    AUTHENTICATION_REQUIRED = "authentication_required"
    CAPTCHA_REQUIRED = "captcha_required"
    PAGE_CHANGED = "page_changed"
    FIELD_MAPPING_FAILED = "field_mapping_failed"
    REQUIRED_ANSWER_MISSING = "required_answer_missing"
    CONFLICTING_ANSWER = "conflicting_answer"
    UPLOAD_FAILED = "upload_failed"
    NAVIGATION_TIMEOUT = "navigation_timeout"
    BROWSER_CLOSED = "browser_closed"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_RESPONSE_INVALID = "model_response_invalid"
    NETWORK_FAILURE = "network_failure"
    JOB_CLOSED = "job_closed"
    FINAL_SUBMIT_ENCOUNTERED = "final_submit_encountered"


class AutomationActionType(str, Enum):
    NAVIGATE = "navigate"
    READ_FIELD = "read_field"
    FILL_TEXT = "fill_text"
    SELECT_OPTION = "select_option"
    TOGGLE_CHECKBOX = "toggle_checkbox"
    UPLOAD_DOCUMENT = "upload_document"
    CLICK_SAFE_NAV = "click_safe_nav"
    SAVE_SCREENSHOT = "save_screenshot"
    PAUSE_FOR_USER = "pause_for_user"
    STOP = "stop"


class ButtonClassification(str, Enum):
    SAFE_NAVIGATION = "safe_navigation"
    MANUAL_ONLY = "manual_only"
    PROHIBITED = "prohibited"


class AnswerLibraryEntry(BaseModel):
    id: str
    normalizedKey: str
    questionVariants: list[str] = Field(default_factory=list)
    answerType: AnswerType = AnswerType.SHORT_TEXT
    value: Any = None
    sensitivityCategory: SensitivityCategory = SensitivityCategory.NONE
    verificationStatus: Literal["verified", "draft", "disabled"] = "verified"
    source: str = "user"
    applicableCountries: list[str] = Field(default_factory=list)
    applicableCompanies: list[str] = Field(default_factory=list)
    applicableProviders: list[str] = Field(default_factory=list)
    createdAt: str
    updatedAt: str
    lastUsedAt: str | None = None


class ApplicationField(BaseModel):
    id: str
    label: str
    normalizedKey: str
    fieldType: str
    required: bool = False
    options: list[str] = Field(default_factory=list)
    helpText: str = ""
    pageNumber: int = 1
    section: str = ""
    classification: AnswerClassification = AnswerClassification.UNKNOWN
    confidence: float = 0.0
    source: str = ""
    proposedValue: Any = None
    websiteValue: Any = None
    filled: bool = False
    differsFromSaved: bool = False
    sensitivityCategory: SensitivityCategory = SensitivityCategory.NONE
    validationStatus: str = "pending"
    updatedAt: str = ""


class ApplicationDraft(BaseModel):
    id: str
    jobId: str
    jobUrl: str
    companyName: str
    roleTitle: str
    provider: ProviderType = ProviderType.UNKNOWN
    status: ApplicationStatus = ApplicationStatus.READY_TO_PREPARE
    currentPage: str = ""
    currentSection: str = ""
    progress: float = 0.0
    profileId: str = ""
    resumeId: str = ""
    coverLetterId: str | None = None
    matchScore: float = 0.0
    fields: list[ApplicationField] = Field(default_factory=list)
    verifiedCount: int = 0
    reviewCount: int = 0
    missingCount: int = 0
    conflictingCount: int = 0
    screenshots: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    browserRunId: str | None = None
    createdAt: str
    updatedAt: str
    lastResumedAt: str | None = None


class DiscoveredJob(BaseModel):
    id: str
    sourceProvider: ProviderType
    company: str
    title: str
    description: str = ""
    responsibilities: str = ""
    requiredQualifications: list[str] = Field(default_factory=list)
    preferredQualifications: list[str] = Field(default_factory=list)
    location: str = ""
    workplaceType: str = ""
    employmentType: str = ""
    salaryMin: float | None = None
    salaryMax: float | None = None
    currency: str = ""
    applicationUrl: str
    listingUrl: str
    externalJobId: str = ""
    datePosted: str = ""
    dateDiscovered: str
    contentHash: str = ""
    active: bool = True
    discoveryRunId: str = ""


class JobMatch(BaseModel):
    jobId: str
    overallScore: float = 0.0
    requiredCoverage: float = 0.0
    preferredCoverage: float = 0.0
    skillOverlap: float = 0.0
    experienceAlignment: float = 0.0
    seniorityAlignment: float = 0.0
    locationAlignment: float = 0.0
    strongMatches: list[str] = Field(default_factory=list)
    missingQualifications: list[str] = Field(default_factory=list)
    potentialConcerns: list[str] = Field(default_factory=list)
    explanation: str = ""


class DiscoveryRun(BaseModel):
    id: str
    careersUrl: str
    status: DiscoveryRunStatus = DiscoveryRunStatus.PENDING
    profileId: str = ""
    resumeId: str = ""
    locationPreferences: list[str] = Field(default_factory=list)
    workplacePreference: str = ""
    minMatchScore: float = 0.0
    includeKeywords: list[str] = Field(default_factory=list)
    excludeKeywords: list[str] = Field(default_factory=list)
    provider: ProviderType = ProviderType.UNKNOWN
    jobsFound: int = 0
    logs: list[dict[str, Any]] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    createdAt: str
    updatedAt: str
    completedAt: str | None = None


class BrowserRun(BaseModel):
    id: str
    applicationId: str
    status: str = "pending"
    headed: bool = True
    tracePath: str = ""
    startedAt: str = ""
    endedAt: str | None = None
    currentUrl: str = ""
    error: dict[str, Any] | None = None


class StructuredError(BaseModel):
    category: ErrorCategory
    message: str
    applicationId: str = ""
    browserRunId: str = ""
    suggestedAction: str = ""
    retryAllowed: bool = False
    pageUrl: str = ""
    timestamp: str = ""


class ApplicationRun(BaseModel):
    id: str
    targetProcessCount: int = 25
    processedCount: int = 0
    submittedCount: int = 0
    stagedCount: int = 0
    skippedCount: int = 0
    failedCount: int = 0
    status: AutopilotRunStatus = AutopilotRunStatus.STOPPED
    startedAt: str
    completedAt: str | None = None
    stoppedAt: str | None = None
    lastHeartbeatAt: str
    currentJobId: str | None = None
    currentJobTitle: str | None = None
    currentCompany: str | None = None
    lastAction: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class JobApplicationItem(BaseModel):
    id: str
    jobId: str
    company: str
    title: str
    applicationUrl: str
    status: AutopilotJobStatus = AutopilotJobStatus.DISCOVERED
    matchScore: float = 0.0
    matchReasons: list[str] = Field(default_factory=list)
    skipReason: str | None = None
    discoveredAt: str
    postedAt: str | None = None
    queuedAt: str | None = None
    applicationStartedAt: str | None = None
    submittedAt: str | None = None
    currentStep: str = ""
    attemptCount: int = 0
    lastError: str | None = None
    lastErrorType: ApplicationErrorType | None = None
    checkpointHistory: list[dict[str, Any]] = Field(default_factory=list)
    answers: dict[str, Any] = Field(default_factory=dict)
    unresolvedQuestions: list[dict[str, Any]] = Field(default_factory=list)
    aiExplanation: str | None = None
    screenshots: list[str] = Field(default_factory=list)
    submissionEvidence: dict[str, Any] | None = None
    lockedBy: str | None = None
    lockedAt: str | None = None
    lockExpiresAt: str | None = None

