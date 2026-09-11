"""Authenticated progress endpoints; never submit applications."""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.routers.application_assistant._common import db_session
from app.services.career_progress import acknowledge_milestone, complete_quest, progress_snapshot, save_preferences

router = APIRouter(prefix="/application-assistant/progress", tags=["career-progress"])


class Preferences(BaseModel):
    weeklyGoal: int = Field(ge=1, le=3, strict=True)
    timezone: str = Field(max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA timezone") from None
        return value


class Completion(BaseModel):
    week: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.get("")
def get_progress(db: Session = Depends(db_session)):
    return progress_snapshot(db)


@router.put("/preferences")
def update_preferences(payload: Preferences, db: Session = Depends(db_session)):
    save_preferences(db, payload.weeklyGoal, payload.timezone)
    return progress_snapshot(db)


@router.post("/quests/{quest_id}/complete")
def check_in(quest_id: str, payload: Completion, db: Session = Depends(db_session)):
    try:
        complete_quest(db, quest_id, payload.week)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return progress_snapshot(db)


@router.post("/milestones/{milestone_id}/seen")
def mark_seen(milestone_id: str, db: Session = Depends(db_session)):
    try:
        acknowledge_milestone(db, milestone_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return progress_snapshot(db)
