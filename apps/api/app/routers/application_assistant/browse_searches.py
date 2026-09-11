"""Persist named browse filters without changing the candidate profile."""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import delete_entity, get_entity, list_entities, upsert_entity
from app.routers.application_assistant._common import db_session

router = APIRouter(prefix="/application-assistant/browse-searches", tags=["browse-searches"])


class SearchFilters(BaseModel):
    q: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=1000)
    company: str = Field(default="", max_length=300)
    specialties: list[str] = Field(default_factory=list, max_length=30)
    seniorities: list[str] = Field(default_factory=list, max_length=10)
    workModes: list[str] = Field(default_factory=list, max_length=10)
    companies: list[str] = Field(default_factory=list, max_length=100)
    experience: str = Field(default="", max_length=30)
    freshness: str = Field(default="all", max_length=10)
    sponsorship: str = Field(default="all", max_length=30)
    sort: str = Field(default="relevancy", max_length=30)


class SavedSearch(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filters: SearchFilters


@router.get("")
def get_searches(db: Session = Depends(db_session)):
    return {"searches": list_entities(db, "browse_search")}


@router.post("")
def save_search(payload: SavedSearch, db: Session = Depends(db_session)):
    if not payload.name.strip():
        raise HTTPException(422, "Give this search a name")
    if len(list_entities(db, "browse_search")) >= 20:
        raise HTTPException(409, "Keep up to 20 saved searches. Remove one before adding another.")
    upsert_entity(db, "browse_search", {"id": f"search-{uuid4().hex}", "name": payload.name.strip(), "filters": payload.filters.model_dump()})
    return get_searches(db)


@router.put("/{search_id}")
def rename_search(search_id: str, payload: SavedSearch, db: Session = Depends(db_session)):
    old = get_entity(db, "browse_search", search_id)
    if not old:
        raise HTTPException(404, "Search not found")
    if not payload.name.strip():
        raise HTTPException(422, "Give this search a name")
    upsert_entity(db, "browse_search", {**old, "name": payload.name.strip(), "filters": payload.filters.model_dump()})
    return get_searches(db)


@router.delete("/{search_id}")
def remove_search(search_id: str, db: Session = Depends(db_session)):
    if not delete_entity(db, "browse_search", search_id):
        raise HTTPException(404, "Search not found")
    return get_searches(db)
