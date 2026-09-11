"""Skill -> evidence map API.

Three questions this answers, all of which used to require reading the tailoring
logs or guessing:

* What evidence do I have for a given skill, and what is my backup?
* For this specific posting, which stories would be sent to the model and why?
* What does this posting ask for that I cannot evidence at all?

The last one matters most. It is the per-posting version of RESUME-GAPS.md, and
it is the honest answer to a match score: a role can score well overall while
the two requirements it actually cares about have nothing behind them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.story_index import (
    EVIDENCE_TIERS,
    build_evidence_brief,
    get_index,
    reset_index_cache,
)

router = APIRouter(prefix="/story-map", tags=["story-map"])


class MatchRequest(BaseModel):
    description: str = Field(default="", description="Full job description text")
    title: str = Field(default="", description="Job title, weighted higher than the body")
    limit: int = Field(default=6, ge=1, le=20)
    charBudget: int = Field(default=9000, ge=500, le=60000)
    includeBrief: bool = Field(
        default=False,
        description="Return the exact text that would be sent to the tailoring model",
    )


@router.get("")
def get_story_map() -> dict[str, Any]:
    """The whole map: every skill, its best evidence and its backups."""
    index = get_index()
    return {
        "skills": index.skill_map(),
        "stories": [s.to_dict() for s in index.stories],
        "evidenceTiers": list(EVIDENCE_TIERS),
        "totals": {
            "stories": len(index.stories),
            "skills": len(index.by_tag),
            "byTier": {
                tier: sum(1 for s in index.stories if s.evidence == tier)
                for tier in EVIDENCE_TIERS
            },
        },
    }


@router.get("/skills/{skill}")
def get_skill(skill: str) -> dict[str, Any]:
    """Everything that evidences one skill, strongest first."""
    index = get_index()
    entry = index.skill_map().get(skill)
    if not entry:
        return {"skill": skill, "found": False, "stories": []}
    return {
        "skill": skill,
        "found": True,
        **entry,
        "stories": [index.by_id[i].to_dict() for i in entry["allStories"]],
    }


@router.post("/match")
def match_posting(payload: MatchRequest) -> dict[str, Any]:
    """Which stories this posting resolves to, and what it asks for that I lack."""
    index = get_index()
    matches = index.select(payload.description, title=payload.title, limit=payload.limit)
    coverage = index.coverage(matches, payload.description, payload.title)
    result: dict[str, Any] = {
        "selected": [
            {
                **m.story.to_dict(),
                "score": m.score,
                "covers": m.covers,
                "alsoDemonstrates": [t for t in m.matched if t not in m.covers],
            }
            for m in matches
        ],
        "coverage": coverage,
        # Named separately because this is the actionable half: these are the
        # requirements no story in the corpus can support.
        "unevidencedRequirements": coverage["uncovered"],
    }
    if payload.includeBrief:
        result["brief"] = build_evidence_brief(matches, char_budget=payload.charBudget)
    return result


@router.post("/reload")
def reload_corpus() -> dict[str, Any]:
    """Re-read the corpus from disk after it has been edited."""
    reset_index_cache()
    index = get_index()
    return {"stories": len(index.stories), "skills": len(index.by_tag)}
