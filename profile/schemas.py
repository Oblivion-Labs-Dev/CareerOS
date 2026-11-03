"""Pydantic request/response models for the profile service."""

from typing import Any

from pydantic import BaseModel


class ProfilePayload(BaseModel):
    profile: dict[str, Any]


class MemoryNotePayload(BaseModel):
    text: str


class PortfolioSettingsPayload(BaseModel):
    isPublic: bool | None = None
    slug: str | None = None
