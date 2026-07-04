import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import JSON, Column, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class KVStore(Base):
    __tablename__ = "kv_store"
    key = Column(String(128), primary_key=True)
    value = Column(JSON, nullable=False)


class EntityStore(Base):
    __tablename__ = "entities"
    id = Column(String(64), primary_key=True)
    entity_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False)


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "career_os.db"
PROFILE_SEED_PATH = DATA_DIR / "applypilot-profile.json"
EXTENSION_DB_PATH = Path(__file__).resolve().parents[3] / "extension" / "db.json"

engine = create_engine(
    settings.career_os_database_url
    if not settings.career_os_database_url.startswith("sqlite:///./")
    else f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False} if "sqlite" in settings.career_os_database_url else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with session_scope() as db:
        if not get_kv(db, "profile"):
            set_kv(db, "profile", load_profile_seed() or default_profile())
        else:
            seed_profile_if_needed(db)
        seed_extension_db_if_needed(db)
        if not get_kv(db, "settings"):
            settings_payload = (load_extension_db() or {}).get("settings")
            set_kv(db, "settings", settings_payload or default_settings())


def load_extension_db() -> dict[str, Any] | None:
    if not EXTENSION_DB_PATH.exists():
        return None
    try:
        return json.loads(EXTENSION_DB_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_profile_seed() -> dict[str, Any] | None:
    extension_db = load_extension_db()
    if extension_db and extension_db.get("profile"):
        return extension_db["profile"]
    if not PROFILE_SEED_PATH.exists():
        return None
    try:
        return json.loads(PROFILE_SEED_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def profile_needs_seed(current: dict[str, Any], seed: dict[str, Any]) -> bool:
    if current.get("email") == "jane.doe@example.com":
        return True
    if not current.get("workExperience") and seed.get("workExperience"):
        return True
    if not current.get("screeningAnswers") and seed.get("screeningAnswers"):
        return True
    identity_keys = ("fullName", "email", "phone")
    current_identity = [str(current.get(key, "")).strip() for key in identity_keys]
    seed_identity = [str(seed.get(key, "")).strip() for key in identity_keys]
    if any(seed_identity) and not any(current_identity):
        return True
    return False


def seed_profile_if_needed(db: Session) -> None:
    """Load extension db.json / applypilot-profile.json when the DB still has placeholder data."""
    seed = load_profile_seed()
    if not seed:
        return
    current = get_kv(db, "profile") or {}
    if not profile_needs_seed(current, seed):
        return
    merged = {**current, **seed}
    for key in (
        "firstName",
        "lastName",
        "fullName",
        "email",
        "phone",
        "location",
        "linkedin",
        "github",
        "portfolio",
        "workExperience",
        "screeningAnswers",
        "customFields",
    ):
        if current.get(key) and not seed.get(key):
            merged[key] = current[key]
    set_kv(db, "profile", merged)


def seed_extension_db_if_needed(db: Session) -> None:
    """Import apps/extension/db.json when the API DB has no synced extension payload yet."""
    payload = load_extension_db()
    if not payload:
        return
    has_applications = entity_count(db, "application") > 0
    has_learned_answers = entity_count(db, "learned_answer") > 0
    documents = get_kv(db, "documents") or {}
    has_resume = bool(documents.get("defaultResume"))
    extension_has_resume = bool(payload.get("documents", {}).get("defaultResume"))
    if has_applications and has_learned_answers and (has_resume or not extension_has_resume):
        return
    import_legacy_db(db, payload)


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    value = str(uuid.uuid4())
    return f"{prefix}{value}" if prefix else value


def get_kv(db: Session, key: str) -> Any | None:
    row = db.get(KVStore, key)
    return row.value if row else None


def set_kv(db: Session, key: str, value: Any) -> None:
    row = db.get(KVStore, key)
    if row:
        row.value = value
    else:
        db.add(KVStore(key=key, value=value))


def list_entities(db: Session, entity_type: str) -> list[dict[str, Any]]:
    rows = db.query(EntityStore).filter(EntityStore.entity_type == entity_type).all()
    return [row.payload for row in rows]


def get_entity(db: Session, entity_type: str, entity_id: str) -> dict[str, Any] | None:
    row = (
        db.query(EntityStore)
        .filter(EntityStore.entity_type == entity_type, EntityStore.id == entity_id)
        .one_or_none()
    )
    return row.payload if row else None


def upsert_entity(db: Session, entity_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    entity_id = payload.get("id") or new_id()
    payload = {**payload, "id": entity_id, "updatedAt": now_iso()}
    row = (
        db.query(EntityStore)
        .filter(EntityStore.entity_type == entity_type, EntityStore.id == entity_id)
        .one_or_none()
    )
    if row:
        row.payload = payload
    else:
        if "createdAt" not in payload:
            payload["createdAt"] = now_iso()
        db.add(EntityStore(id=entity_id, entity_type=entity_type, payload=payload))
    return payload


def patch_entity(db: Session, entity_type: str, entity_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    current = get_entity(db, entity_type, entity_id)
    if not current:
        return None
    merged = {**current, **patch, "id": entity_id, "updatedAt": now_iso()}
    upsert_entity(db, entity_type, merged)
    return merged


def default_profile() -> dict[str, Any]:
    return {
        "firstName": "Jane",
        "lastName": "Doe",
        "fullName": "Jane Doe",
        "email": "jane.doe@example.com",
        "phone": "+1 (555) 123-4567",
        "location": "San Francisco, CA",
        "linkedin": "https://linkedin.com/in/username",
        "github": "https://github.com/username",
        "portfolio": "https://janedoe.dev",
        "workAuthorization": "Yes",
        "sponsorship": "No",
        "yearsExperience": "5",
        "currentTitle": "Software Engineer",
        "targetRole": "Senior Engineer",
        "salaryExpectations": "$140,000",
    }


def default_settings() -> dict[str, Any]:
    return {
        "autofillLog": {
            "unrecognizedFields": True,
            "missingProfileValue": True,
            "fillReturnedFalse": True,
            "stillEmpty": True,
            "skippedByRule": False,
        },
        "submitTracker": {
            "enabled": True,
            "finalSubmitOnly": True,
            "submitButtonPatterns": [
                "\\bsubmit\\b",
                "send application",
                "complete application",
            ],
            "continueButtonPatterns": ["save and continue", "\\bnext\\b"],
            "requireJobPageUrl": True,
            "dedupeMinutes": 60,
            "showToast": True,
        },
    }


def entity_count(db: Session, entity_type: str) -> int:
    return db.query(EntityStore).filter(EntityStore.entity_type == entity_type).count()


def tracker_summary(db: Session) -> dict[str, Any]:
    """Lightweight tracker payload for the web dashboard (no resume binary)."""
    return {
        "applications": list_entities(db, "application"),
        "jobsCount": entity_count(db, "job"),
        "mappingsCount": entity_count(db, "field_mapping"),
        "learnedAnswersCount": entity_count(db, "learned_answer"),
        "sessionsCount": entity_count(db, "autofill_session"),
    }


def legacy_db_snapshot(db: Session) -> dict[str, Any]:
    """Compatibility payload for Chrome extension sync (/api/db)."""
    profile = get_kv(db, "profile") or default_profile()
    documents = get_kv(db, "documents") or {"defaultResume": None, "defaultCoverLetter": None}
    settings_data = get_kv(db, "settings") or default_settings()
    return {
        "profile": profile,
        "documents": documents,
        "applications": list_entities(db, "application"),
        "jobs": list_entities(db, "job"),
        "learnedAnswers": list_entities(db, "learned_answer"),
        "sessions": list_entities(db, "autofill_session"),
        "fieldMappings": list_entities(db, "field_mapping"),
        "activityEvents": list_entities(db, "career_event"),
        "referrals": list_entities(db, "referral"),
        "settings": settings_data,
    }


def import_legacy_db(db: Session, payload: dict[str, Any]) -> None:
    if payload.get("profile"):
        set_kv(db, "profile", payload["profile"])
    if payload.get("documents"):
        set_kv(db, "documents", payload["documents"])
    if payload.get("settings"):
        set_kv(db, "settings", payload["settings"])
    for app in payload.get("applications", []):
        upsert_entity(db, "application", normalize_application(app))
    for job in payload.get("jobs", []):
        upsert_entity(db, "job", normalize_job(job))
    for qa in payload.get("learnedAnswers", []):
        upsert_entity(db, "learned_answer", qa)
    for session in payload.get("sessions", []):
        upsert_entity(db, "autofill_session", session)
    for mapping in payload.get("fieldMappings", []):
        upsert_entity(db, "field_mapping", mapping)
    for event in payload.get("activityEvents", []):
        upsert_entity(db, "career_event", event)
    for referral in payload.get("referrals", []):
        upsert_entity(db, "referral", referral)


def normalize_application(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status", "saved")
    if status == "interview":
        status = "interviewing"
    return {
        "id": raw.get("id") or new_id("app_"),
        "jobId": raw.get("jobId"),
        "companyId": raw.get("companyId"),
        "companyName": raw.get("companyName") or raw.get("company") or "Unknown",
        "roleTitle": raw.get("roleTitle") or raw.get("role") or "Unknown role",
        "status": status,
        "priority": raw.get("priority", "medium"),
        "url": raw.get("url") or raw.get("notes", ""),
        "resumeUsedId": raw.get("resumeUsedId") or raw.get("resumeUsed"),
        "coverLetterUsedId": raw.get("coverLetterUsedId") or raw.get("coverLetterUsed"),
        "notes": raw.get("notes", ""),
        "updatedAt": raw.get("updatedAt") or raw.get("date") or now_iso(),
    }


def normalize_job(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id") or new_id("job_"),
        "companyName": raw.get("companyName") or raw.get("company") or "Unknown",
        "title": raw.get("title") or raw.get("role") or "Unknown",
        "location": raw.get("location", ""),
        "description": raw.get("description", ""),
        "url": raw.get("url", ""),
        "platform": raw.get("platform", ""),
        "savedAt": raw.get("savedAt") or now_iso(),
    }
