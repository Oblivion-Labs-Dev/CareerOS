import json
import logging
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import JSON, Column, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.db.resume_corpus_seed import (
    load_resume_corpus_seed,
    resume_corpus_seed_to_accomplishment,
)


class Base(DeclarativeBase):
    pass


class KVStore(Base):
    __tablename__ = "kv_store"
    user_id = Column(String(64), primary_key=True, default="default")
    key = Column(String(128), primary_key=True)
    value = Column(JSON, nullable=False)


class EntityStore(Base):
    __tablename__ = "entities"
    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=False, default="default", index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    payload = Column(JSON, nullable=False)


_JSON_PATH = re.compile(r"^\$(\.[A-Za-z_][A-Za-z0-9_]*)+$")


def json_field(path: str):
    """Dialect-aware JSON field extraction.
    For SQLite: uses ``json_extract(payload, '<path>')`` matching expression indexes.
    For PostgreSQL: uses ``func.json_extract_path_text(EntityStore.payload, *path_elements)``.
    """
    from sqlalchemy import func, literal_column

    if not _JSON_PATH.match(path):
        raise ValueError(f"not a plain JSON path: {path!r}")

    if "sqlite" in str(engine.url):
        return func.json_extract(EntityStore.payload, literal_column(f"'{path}'"))
    else:
        parts = [p for p in path.lstrip("$.").split(".") if p]
        return func.json_extract_path_text(EntityStore.payload, *parts)


DATA_DIR =Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "career_os.db"
PROFILE_SEED_PATH = DATA_DIR / "applypilot-profile.json"
EXTENSION_DB_PATH = Path(__file__).resolve().parents[3] / "extension" / "db.json"
RESUME_CORPUS_SEED_PATH = Path(__file__).resolve().parents[4] / "data" / "resume-corpus-initial.json"

_raw_db_url = settings.career_os_database_url
if _raw_db_url.startswith("sqlite:///./"):
    _db_url = f"sqlite:///{DB_PATH.as_posix()}"
else:
    _db_url = _raw_db_url

_is_sqlite = "sqlite" in _db_url

_connect_args = {"check_same_thread": False, "timeout": 60.0} if _is_sqlite else {}
_engine_kwargs: dict[str, Any] = {
    "connect_args": _connect_args,
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
_engine_kwargs["pool_size"] = 10
_engine_kwargs["max_overflow"] = 20

engine = create_engine(_db_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


from sqlalchemy import event


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in str(engine.url):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


# Expression indexes over the JSON payload. The table only had an index on
# entity_type, so every "which jobs are QUEUED" lookup loaded the whole
# partition for its type and filtered in Python after parsing each row. These
# push the two hottest predicates into SQLite:
#
#   status          - every queue and dashboard read filters on it
#   applicationUrl  - the duplicate-application sweep looks up siblings by it,
#                     which was a full scan on every submission
#
# CREATE INDEX IF NOT EXISTS is idempotent, so this runs safely at every start.
_SQLITE_JSON_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_entities_status",
        "CREATE INDEX IF NOT EXISTS ix_entities_status "
        "ON entities (entity_type, json_extract(payload, '$.status'))",
    ),
    (
        "ix_entities_application_url",
        "CREATE INDEX IF NOT EXISTS ix_entities_application_url "
        "ON entities (entity_type, json_extract(payload, '$.applicationUrl'))",
    ),
    (
        # The discover page asks "which postings were added to the assistant"
        # on nearly every request: 51 of ~11k discovered rows, found by a full
        # scan that parsed every payload.
        "ix_entities_added_to_assistant",
        "CREATE INDEX IF NOT EXISTS ix_entities_added_to_assistant "
        "ON entities (entity_type, json_extract(payload, '$.addedToAssistant'))",
    ),
)

_PG_JSON_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_entities_status_pg",
        "CREATE INDEX IF NOT EXISTS ix_entities_status_pg "
        "ON entities (entity_type, (payload->>'status'))",
    ),
    (
        "ix_entities_application_url_pg",
        "CREATE INDEX IF NOT EXISTS ix_entities_application_url_pg "
        "ON entities (entity_type, (payload->>'applicationUrl'))",
    ),
    (
        "ix_entities_added_to_assistant_pg",
        "CREATE INDEX IF NOT EXISTS ix_entities_added_to_assistant_pg "
        "ON entities (entity_type, (payload->>'addedToAssistant'))",
    ),
)


def _configure_sqlite() -> None:
    from sqlalchemy import text

    if "sqlite" in str(engine.url):
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA busy_timeout=60000"))
            # Reclaim space after the retention sweep deletes rows. Without this the
            # file only ever grows: SQLite keeps freed pages for reuse and never
            # returns them to the filesystem.
            conn.execute(text("PRAGMA auto_vacuum=INCREMENTAL"))
            for name, ddl in _SQLITE_JSON_INDEXES:
                try:
                    conn.execute(text(ddl))
                except Exception:  # noqa: BLE001 - an index is an optimisation, never a boot blocker
                    logging.getLogger("career_os.db").warning("Could not create %s", name)
            conn.commit()
    else:
        with engine.connect() as conn:
            for name, ddl in _PG_JSON_INDEXES:
                try:
                    conn.execute(text(ddl))
                except Exception:  # noqa: BLE001 - an index is an optimisation, never a boot blocker
                    logging.getLogger("career_os.db").warning("Could not create %s", name)
            conn.commit()


def _migrate_schema_if_needed() -> None:
    """Safely migrate existing SQLite or Postgres tables to add user_id column
    and composite primary key without losing any data."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    table_names = set(insp.get_table_names())

    with engine.connect() as conn:
        if "entities" in table_names:
            cols = {c["name"] for c in insp.get_columns("entities")}
            if "user_id" not in cols:
                conn.execute(text("ALTER TABLE entities ADD COLUMN user_id VARCHAR(64) DEFAULT 'default' NOT NULL"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_entities_user_id ON entities (user_id)"))
                conn.commit()

        if "kv_store" in table_names:
            pk_cols = set(insp.get_pk_constraint("kv_store").get("constrained_columns", []))
            if pk_cols != {"user_id", "key"}:
                if "sqlite" in str(engine.url):
                    cols_kv = {c["name"] for c in insp.get_columns("kv_store")}
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS kv_store_new (
                            user_id VARCHAR(64) NOT NULL DEFAULT 'default',
                            key VARCHAR(128) NOT NULL,
                            value JSON NOT NULL,
                            PRIMARY KEY (user_id, key)
                        )
                    """))
                    if "user_id" in cols_kv:
                        conn.execute(text("INSERT OR IGNORE INTO kv_store_new (user_id, key, value) SELECT user_id, key, value FROM kv_store"))
                    else:
                        conn.execute(text("INSERT OR IGNORE INTO kv_store_new (user_id, key, value) SELECT 'default', key, value FROM kv_store"))
                    conn.execute(text("DROP TABLE kv_store"))
                    conn.execute(text("ALTER TABLE kv_store_new RENAME TO kv_store"))
                    conn.commit()
                else:
                    cols_kv = {c["name"] for c in insp.get_columns("kv_store")}
                    if "user_id" not in cols_kv:
                        conn.execute(text("ALTER TABLE kv_store ADD COLUMN user_id VARCHAR(64) DEFAULT 'default' NOT NULL"))
                    conn.execute(text("ALTER TABLE kv_store DROP CONSTRAINT IF EXISTS kv_store_pkey"))
                    conn.execute(text("ALTER TABLE kv_store ADD PRIMARY KEY (user_id, key)"))
                    conn.commit()


def init_db() -> None:
    _migrate_schema_if_needed()
    Base.metadata.create_all(bind=engine)
    _configure_sqlite()
    skip_extension_seed = os.environ.get("CAREER_OS_SKIP_EXTENSION_SEED") == "1"
    with session_scope() as db:
        if not get_kv(db, "profile"):
            seed_profile = None if skip_extension_seed else load_profile_seed()
            set_kv(db, "profile", seed_profile or default_profile())
        elif not skip_extension_seed:
            seed_profile_if_needed(db)
        if not skip_extension_seed:
            seed_extension_db_if_needed(db)
        seed_resume_corpus_if_needed(db)
        # Fold the interview story corpus into those accomplishments. Runs every
        # start rather than once, so editing the corpus file is enough to update
        # the app; the merge is enrich-only, so repeating it is a no-op.
        try:
            from app.db.story_corpus_sync import sync_story_corpus

            sync_story_corpus(db)
        except Exception:  # noqa: BLE001 - a corpus problem must not stop startup
            logging.getLogger("career_os.db").exception(
                "Story corpus sync failed; continuing without it"
            )
        if not get_kv(db, "settings"):
            settings_payload = None if skip_extension_seed else (load_extension_db() or {}).get("settings")
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
    return datetime.now(UTC).isoformat()


def new_id(prefix: str = "") -> str:
    value = str(uuid.uuid4())
    return f"{prefix}{value}" if prefix else value


def _pending_kv(db: Session, key: str, user_id: str = "default") -> KVStore | None:
    return next(
        (
            row
            for row in db.new
            if isinstance(row, KVStore) and row.key == key and getattr(row, "user_id", "default") == user_id
        ),
        None,
    )


def get_kv(db: Session, key: str, user_id: str = "default") -> Any | None:
    row = _pending_kv(db, key, user_id) or db.get(KVStore, (user_id, key))
    return row.value if row else None


def set_kv(db: Session, key: str, value: Any, user_id: str = "default") -> None:
    row = _pending_kv(db, key, user_id) or db.get(KVStore, (user_id, key))
    if row:
        row.value = value
    else:
        db.add(KVStore(user_id=user_id, key=key, value=value))


def list_entities(db: Session, entity_type: str, user_id: str | None = None) -> list[dict[str, Any]]:
    query = db.query(EntityStore).filter(EntityStore.entity_type == entity_type)
    if user_id is not None:
        query = query.filter(EntityStore.user_id == user_id)
    rows = query.all()
    return [row.payload for row in rows]


def list_entities_where_json(
    db: Session, entity_type: str, json_path: str, *, truthy: bool = True, user_id: str | None = None
) -> list[dict[str, Any]]:
    """Entities filtered by a JSON field, without deserialising every row.

    `list_entities` loads and parses the whole table for its type and then
    filters in Python. That is fine for a handful of rows, but the discovered-job
    table is large and the dashboard was paying ~0.5s per page load to find the
    two dozen rows flagged as added-to-assistant. Push the predicate into SQLite
    via json_extract so only the matching rows come back.

    `json_path` is a JSON path such as "$.addedToAssistant".
    """
    from sqlalchemy import func

    extracted = json_field(json_path)
    query = db.query(EntityStore).filter(EntityStore.entity_type == entity_type)
    if user_id is not None:
        query = query.filter(EntityStore.user_id == user_id)
    if truthy:
        # SQLite json_extract yields 1/0 for booleans and the raw value
        # otherwise; both "false" spellings must be excluded. `> 0` (not
        # `IS NOT NULL AND != 0`) so SQLite can range-scan the expression index;
        # NULL fails it, and text sorts above numbers so "true" still passes.
        query = query.filter(extracted > 0).filter(extracted != "false")
    return [row.payload for row in query.all()]


def list_entities_by_json_equals(
    db: Session, entity_type: str, json_path: str, value: Any, user_id: str | None = None
) -> list[dict[str, Any]]:
    """Entities whose JSON field equals `value`, resolved by index.

    Pairs with the expression indexes created in _configure_sqlite. Callers used
    to load the whole partition for their type and compare in Python, which is
    how a status filter over thousands of rows became a full scan plus a JSON
    parse per row.
    """
    from sqlalchemy import func

    extracted = json_field(json_path)
    query = (
        db.query(EntityStore)
        .filter(EntityStore.entity_type == entity_type)
        .filter(extracted == value)
    )
    if user_id is not None:
        query = query.filter(EntityStore.user_id == user_id)
    rows = query.all()
    return [row.payload for row in rows]


def get_entity(db: Session, entity_type: str, entity_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    query = db.query(EntityStore).filter(EntityStore.entity_type == entity_type, EntityStore.id == entity_id)
    if user_id is not None:
        query = query.filter(EntityStore.user_id == user_id)
    row = query.one_or_none()
    return row.payload if row else None


def upsert_entity(db: Session, entity_type: str, payload: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    entity_id = payload.get("id") or new_id()
    uid = user_id or payload.get("userId") or "default"
    payload = {**payload, "id": entity_id, "userId": uid, "updatedAt": now_iso()}
    row = (
        db.query(EntityStore)
        .filter(EntityStore.entity_type == entity_type, EntityStore.id == entity_id)
        .one_or_none()
    )
    if row:
        row.payload = payload
        row.user_id = uid
    else:
        if "createdAt" not in payload:
            payload["createdAt"] = now_iso()
        db.add(EntityStore(id=entity_id, user_id=uid, entity_type=entity_type, payload=payload))
    db.flush()
    return payload


def delete_entity(db: Session, entity_type: str, entity_id: str, user_id: str | None = None) -> bool:
    query = db.query(EntityStore).filter(EntityStore.entity_type == entity_type, EntityStore.id == entity_id)
    if user_id is not None:
        query = query.filter(EntityStore.user_id == user_id)
    row = query.one_or_none()
    if row:
        db.delete(row)
        db.flush()
        return True
    return False



def seed_resume_corpus_if_needed(
    db: Session,
    seed_records: list[dict[str, Any]] | None = None,
) -> int:
    """Insert only seed accomplishment IDs that are absent; never overwrite user records."""
    records = (
        load_resume_corpus_seed(RESUME_CORPUS_SEED_PATH)
        if seed_records is None
        else seed_records
    )
    existing_ids = {
        entity_id
        for (entity_id,) in db.query(EntityStore.id)
        .filter(EntityStore.entity_type == "accomplishment")
        .all()
    }
    imported = 0
    for seed in records:
        seed_id = str(seed.get("id", "")).strip()
        if not seed_id or seed_id in existing_ids:
            continue
        upsert_entity(db, "accomplishment", resume_corpus_seed_to_accomplishment(seed))
        existing_ids.add(seed_id)
        imported += 1
    return imported


def patch_entity(
    db: Session, entity_type: str, entity_id: str, patch: dict[str, Any], user_id: str | None = None
) -> dict[str, Any] | None:
    current = get_entity(db, entity_type, entity_id, user_id=user_id)
    if not current:
        return None
    merged = {**current, **patch, "id": entity_id, "updatedAt": now_iso()}
    upsert_entity(db, entity_type, merged, user_id=user_id)
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
        "currentCompany": "Example Corp",
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


def entity_count(db: Session, entity_type: str, user_id: str | None = None) -> int:
    query = db.query(EntityStore).filter(EntityStore.entity_type == entity_type)
    if user_id is not None:
        query = query.filter(EntityStore.user_id == user_id)
    return query.count()


def tracker_summary(db: Session) -> dict[str, Any]:
    """Lightweight tracker payload for the web dashboard (no resume binary)."""
    raw_applications = [enrich_application_record(app) for app in list_entities(db, "application")]
    # Exclude Gmail-synced entries when Gmail sync is disabled to prevent duplicate counts
    applications = [
        a for a in raw_applications
        if a.get("source") not in ("careeros", "gmail_manual") and not str(a.get("id", "")).startswith("gmail_")
    ]

    # Autopilot jobs tracked internally in aa_autopilot_job (source of truth)
    autopilot_submitted = sum(
        1 for j in list_entities(db, "aa_autopilot_job") if j.get("status") == "SUBMITTED"
    )

    # Gmail sync is disabled for now to eliminate duplicate counting
    manual_submitted = 0
    total_submitted = autopilot_submitted

    return {
        "applications": applications,
        "jobsCount": entity_count(db, "job"),
        "mappingsCount": entity_count(db, "field_mapping"),
        "learnedAnswersCount": entity_count(db, "learned_answer"),
        "sessionsCount": entity_count(db, "autofill_session"),
        "autopilotSubmittedCount": autopilot_submitted,
        "manualSubmittedCount": manual_submitted,
        "totalSubmittedCount": total_submitted,
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


def parse_company_from_job_url(url: str) -> str | None:
    if not url:
        return None
    try:
        path = urlparse(url).path
        greenhouse = re.search(r"/([^/]+)/jobs/\d+", path, re.I)
        if greenhouse and greenhouse.group(1).lower() not in {"embed", "job_app"}:
            slug = re.sub(r"[-_]+", " ", greenhouse.group(1)).strip()
            return " ".join(part.capitalize() for part in slug.split())
        workday = re.search(r"/recruiting/([^/]+)", path, re.I)
        if workday:
            slug = re.sub(r"[-_]+", " ", workday.group(1)).strip()
            return " ".join(part.capitalize() for part in slug.split())
        ashby = re.search(r"^/([^/]+)(?:/|$)", path, re.I)
        if ashby and ashby.group(1).lower() not in {"api", "embed", "jobs", "postings"}:
            if "ashbyhq.com" in urlparse(url).netloc.lower():
                slug = re.sub(r"[-_]+", " ", ashby.group(1)).strip()
                return " ".join(part.capitalize() for part in slug.split())
    except Exception:
        return None
    return None


def enrich_application_record(raw: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(raw)
    company = str(enriched.get("companyName") or enriched.get("company") or "").strip()
    if company.lower() in {"", "unknown", "unknown company", "workday client", "ashby client"}:
        parsed = parse_company_from_job_url(str(enriched.get("url") or enriched.get("notes") or ""))
        if parsed:
            enriched["companyName"] = parsed
    role = str(enriched.get("roleTitle") or enriched.get("role") or "").strip()
    if role.lower() in {"", "unknown", "unknown role"}:
        url = str(enriched.get("url") or enriched.get("notes") or "")
        workday_role = re.search(r"/job/[^/]+/([^/?#]+)", url, re.I)
        if workday_role:
            slug = re.sub(r"[-_]+", " ", workday_role.group(1)).strip()
            enriched["roleTitle"] = " ".join(part.capitalize() for part in slug.split())
    return enriched


def normalize_application(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status", "saved")
    if status == "interview":
        status = "interviewing"
    url = raw.get("url") or raw.get("notes", "")
    company = raw.get("companyName") or raw.get("company") or "Unknown"
    if str(company).lower() in {"unknown", "unknown company", "workday client", "ashby client"}:
        parsed_company = parse_company_from_job_url(str(url))
        if parsed_company:
            company = parsed_company
    role = raw.get("roleTitle") or raw.get("role") or "Unknown role"
    if str(role).lower() in {"unknown", "unknown role"}:
        workday_role = re.search(r"/job/[^/]+/([^/?#]+)", str(url), re.I)
        if workday_role:
            slug = re.sub(r"[-_]+", " ", workday_role.group(1)).strip()
            role = " ".join(part.capitalize() for part in slug.split())
    return {
        "id": raw.get("id") or new_id("app_"),
        "jobId": raw.get("jobId"),
        "companyId": raw.get("companyId"),
        "companyName": company,
        "roleTitle": role,
        "location": raw.get("location", ""),
        "platform": raw.get("platform", ""),
        "source": raw.get("source", ""),
        "status": status,
        "priority": raw.get("priority", "medium"),
        "url": raw.get("url") or raw.get("notes", ""),
        "resumeUsedId": raw.get("resumeUsedId") or raw.get("resumeUsed"),
        "coverLetterUsedId": raw.get("coverLetterUsedId") or raw.get("coverLetterUsed"),
        "notes": raw.get("notes", ""),
        "submittedAt": raw.get("submittedAt") or raw.get("appliedAt"),
        "createdAt": raw.get("createdAt") or raw.get("updatedAt") or now_iso(),
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


# Note: a second, older `delete_entity` definition used to live here and
# silently shadowed the real one above (missing `db.flush()`, so a delete
# followed by a read in the same request — autoflush is off — saw stale
# data). Removed as a duplicate; the flushing version above is authoritative.
