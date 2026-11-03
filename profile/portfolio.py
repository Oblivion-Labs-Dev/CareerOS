"""Public, shareable portfolio page settings and sanitized public payload.

The public payload deliberately excludes contact/personal-sensitive fields
(email, phone, work authorization, demographic questionnaire answers, etc.)
— only a name, headline, top skills (aggregated from the accomplishment
corpus), and a handful of accomplishment summaries are ever returned.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, list_entities, set_kv

KV_PORTFOLIO_SETTINGS = "portfolio_settings"

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def default_portfolio_settings() -> dict[str, Any]:
    return {"isPublic": False, "slug": ""}


def get_portfolio_settings(db: Session) -> dict[str, Any]:
    stored = get_kv(db, KV_PORTFOLIO_SETTINGS)
    return {**default_portfolio_settings(), **(stored or {})}


def normalize_slug(raw: str) -> str:
    slug = raw.strip().lower().replace(" ", "-")
    slug = _SLUG_RE.sub("", slug)
    return slug[:60]


def save_portfolio_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    current = get_portfolio_settings(db)
    merged = {**current, **patch}
    if "slug" in patch:
        merged["slug"] = normalize_slug(str(patch["slug"] or ""))
    if merged.get("isPublic") and not merged.get("slug"):
        raise ValueError("Set a slug before making your portfolio public")
    set_kv(db, KV_PORTFOLIO_SETTINGS, merged)
    return merged


def _top_skills(accomplishments: list[dict[str, Any]], limit: int = 12) -> list[str]:
    counter: Counter[str] = Counter()
    for acc in accomplishments:
        for skill in acc.get("techStack") or []:
            if isinstance(skill, str) and skill.strip():
                counter[skill.strip()] += 1
    return [skill for skill, _ in counter.most_common(limit)]


def _select_accomplishments(accomplishments: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    out = []
    for acc in accomplishments[:limit]:
        problem = acc.get("problemContext") or {}
        summary = str(problem.get("what") or "").strip()
        out.append(
            {
                "company": str(acc.get("company") or ""),
                "project": str(acc.get("project") or ""),
                "summary": summary,
            }
        )
    return out


def build_public_portfolio(db: Session, slug: str) -> dict[str, Any] | None:
    settings = get_portfolio_settings(db)
    if not settings.get("isPublic") or normalize_slug(slug) != settings.get("slug"):
        return None

    profile = get_kv(db, "profile") or {}
    accomplishments = list_entities(db, "accomplishment")

    return {
        "name": profile.get("fullName") or "",
        "headline": profile.get("currentTitle") or profile.get("targetRole") or "",
        "location": profile.get("location") or "",
        "yearsExperience": profile.get("yearsExperience"),
        "skills": _top_skills(accomplishments),
        "accomplishments": _select_accomplishments(accomplishments),
        "experience": [
            {
                "company": str(item.get("company") or ""),
                "title": str(item.get("jobTitle") or ""),
                "startDate": str(item.get("startDate") or ""),
                "endDate": str(item.get("endDate") or ("Present" if item.get("currentlyEmployed") else "")),
            }
            for item in (profile.get("workExperience") or [])
        ],
    }
