"""Shared database primitives: the declarative Base, the engine, the session
factory, and the two tiny id/timestamp helpers.

This is cross-cutting infrastructure with no business logic. Table models
(``KVStore``, ``EntityStore``) and all the entity CRUD helpers remain in their
owning module (``app.db.store`` during the transition); they build on the
``Base`` and ``session_scope`` defined here.

During the modular-monolith refactor ``app.db.store`` re-exports these names so
existing ``from app.db.store import engine`` call sites keep working untouched.
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


# The repository root is four parents up from this file
# (shared/db.py -> shared -> <repo root>). The SQLite file lives under
# apps/api/data so the location is unchanged from when this lived in
# apps/api/app/db/store.py (which computed parents[2] from app/db/store.py).
DATA_DIR = Path(__file__).resolve().parents[1] / "apps" / "api" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "career_os.db"

engine = create_engine(
    settings.career_os_database_url
    if not settings.career_os_database_url.startswith("sqlite:///./")
    else f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 60.0},
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


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
_JSON_INDEXES: tuple[tuple[str, str], ...] = (
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


def configure_sqlite() -> None:
    if "sqlite" not in str(engine.url):
        return
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=60000"))
        # Reclaim space after the retention sweep deletes rows. Without this the
        # file only ever grows: SQLite keeps freed pages for reuse and never
        # returns them to the filesystem.
        conn.execute(text("PRAGMA auto_vacuum=INCREMENTAL"))
        for name, ddl in _JSON_INDEXES:
            try:
                conn.execute(text(ddl))
            except Exception:  # noqa: BLE001 - an index is an optimisation, never a boot blocker
                logging.getLogger("career_os.db").warning("Could not create %s", name)
        conn.commit()


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
