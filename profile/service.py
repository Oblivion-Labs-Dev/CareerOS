"""Profile service — business logic for the flat candidate profile fields.

This is the read/write of the ``profile`` KV record used by application forms
(identity, work authorisation, salary, screening answers). It does NOT own
resume files (``resume/``) or the experience corpus used for intelligence
(``intelligence/``).
"""

from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, set_kv
from profile.normalizer import normalize_work_authorization


def get_profile(db: Session) -> dict[str, Any]:
    return get_kv(db, "profile")


def update_profile(db: Session, profile: dict[str, Any]) -> dict[str, Any]:
    # Work-authorization facts are stored under several keys that grew up at
    # different times, and the answer resolver trusts the structured
    # workAuth.* booleans. Without this, editing the flat field in the Profile
    # form changed nothing the resolver could see: the stale nested boolean
    # kept winning, and applications kept going out with the old answer.
    normalized = normalize_work_authorization(profile)
    set_kv(db, "profile", normalized)
    return normalized
