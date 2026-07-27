from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from repair_orchestrator.config import settings


class Base(DeclarativeBase):
    pass


class IncidentRow(Base):
    __tablename__ = "incidents"

    fingerprint = Column(String(64), primary_key=True)
    title = Column(String(255), nullable=False)
    severity = Column(String(32), nullable=False)
    component = Column(String(128), nullable=False)
    occurrence_count = Column(Integer, default=0)
    first_seen = Column(String(64), nullable=False)
    last_seen = Column(String(64), nullable=False)
    status = Column(String(64), default="open")
    latest_message = Column(Text, default="")
    latest_stack = Column(Text, default="")
    metadata_json = Column(Text, default="{}")


class ErrorEventRow(Base):
    __tablename__ = "error_events"

    id = Column(String(36), primary_key=True)
    fingerprint = Column(String(64), nullable=False, index=True)
    payload_json = Column(Text, nullable=False)
    received_at = Column(String(64), nullable=False)


class RepairTaskRow(Base):
    __tablename__ = "repair_tasks"

    task_id = Column(String(36), primary_key=True)
    incident_fingerprint = Column(String(64), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False)
    component = Column(String(128), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(String(64), nullable=False)
    updated_at = Column(String(64), nullable=False)


class AgentRunRow(Base):
    __tablename__ = "agent_runs"

    run_id = Column(String(36), primary_key=True)
    task_id = Column(String(36), nullable=False, index=True)
    adapter = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(String(64), nullable=False)


class AuditRow(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(64), nullable=False)
    action = Column(String(128), nullable=False)
    details_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        db_path = Path(url.replace("sqlite:///", ""))
        db_path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.repair_database_url)
engine = create_engine(settings.repair_database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def load_json(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default if default is not None else {}
    return json.loads(raw)
