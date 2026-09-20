"""Application Assistant API routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import get_kv, now_iso, session_scope
from app.services.application_assistant.browser_runner import close_session
from app.services.application_assistant.job_discovery import (
    cancel_discovery,
    filter_jobs,
    run_discovery,
)
from app.services.application_assistant.llm_client import create_llm_client
from app.services.application_assistant.persistence import (
    create_application_draft,
    create_discovery_run,
    delete_answer,
    get_active_browser_run_for_app,
    get_application_draft,
    get_discovered_job,
    get_discovery_run,
    get_job_match,
    get_settings,
    list_answer_library,
    list_application_drafts,
    list_discovered_jobs,
    list_discovery_runs,
    save_application_fields,
    save_job_match,
    save_settings,
    update_application_draft,
    update_browser_run,
    upsert_answer,
    upsert_discovered_job,
)
from app.services.application_assistant.providers import list_providers
from app.services.application_assistant.url_validation import validate_url
from app.services.application_assistant.worker import (
    is_app_locked,
    run_in_background,
    task_status,
)

def db_session():
    with session_scope() as db:
        yield db


# ── Request Models ────────────────────────────────────────────────────────────

class DiscoveryStartPayload(BaseModel):
    careersUrl: str
    resumeId: str = ""
    locationPreferences: list[str] = Field(default_factory=list)
    workplacePreference: str = ""
    minMatchScore: float = 0
    includeKeywords: list[str] = Field(default_factory=list)
    excludeKeywords: list[str] = Field(default_factory=list)


class ApplicationCreatePayload(BaseModel):
    jobId: str
    resumeId: str = ""


class QuickAddApplicationPayload(BaseModel):
    url: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description: str | None = None
    resumeId: str = ""


class FieldEditPayload(BaseModel):
    fieldId: str
    value: Any
    approved: bool = False


class FieldAnswerSubmission(BaseModel):
    fieldId: str = ""
    normalizedKey: str = ""
    value: Any = None
    profileKey: str = ""


class FieldAnswersPayload(BaseModel):
    answers: list[FieldAnswerSubmission] = Field(default_factory=list)


class UnifiedAnswerTarget(BaseModel):
    appId: str
    fieldId: str
    normalizedKey: str = ""
    label: str = ""
    companyName: str = ""


class UnifiedFieldAnswerSubmission(BaseModel):
    canonicalId: str
    value: Any = None
    profileKey: str = ""
    normalizedKey: str = ""
    targets: list[UnifiedAnswerTarget] = Field(default_factory=list)


class UnifiedFieldAnswersPayload(BaseModel):
    answers: list[UnifiedFieldAnswerSubmission] = Field(default_factory=list)


class AnswerPayload(BaseModel):
    normalizedKey: str
    questionVariants: list[str] = Field(default_factory=list)
    answerType: str = "short_text"
    value: Any = None
    sensitivityCategory: str = "none"
    verificationStatus: str = "verified"
    applicableCompanies: list[str] = Field(default_factory=list)
    applicableProviders: list[str] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    enabled: bool | None = None
    tailoringMode: str | None = None
    allowInferredAnswers: bool | None = None
    llm: dict[str, Any] | None = None
    browser: dict[str, Any] | None = None
    fieldMapping: dict[str, Any] | None = None
    domainAllowlist: list[str] | None = None
    companyBlacklist: list[dict[str, Any]] | None = None


class QwenChatPayload(BaseModel):
    message: str
    history: list[dict[str, str]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class QwenAgentPreparePayload(BaseModel):
    jobId: str = ""
    applicationId: str = ""


class OpenReviewPayload(BaseModel):
    force: bool = False


class ScraperImportPayload(BaseModel):
    scraperJobId: str


class GenerateAnswerPayload(BaseModel):
    question: str
    company: str = ""
    role: str = ""
    jobDescription: str = ""


