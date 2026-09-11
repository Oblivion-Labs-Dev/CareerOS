"""Retention sweep for the entity tables that otherwise grow without bound.

Only the job-discovery snapshot had a retention policy (90 days). Everything
else accumulated for the life of the install: discovered jobs, the form-field
schemas captured per application, autopilot run records, and model usage
events. On this instance that is 50 MB of discovered jobs and ~13k form-field
rows in a 135 MB database, none of which anything deletes.

Two deliberate choices:

* **Dry run by default.** Deleting rows is irreversible and some of these tables
  are referenced by live applications, so the sweep reports what it would remove
  and changes nothing until CAREEROS_RETENTION_ENABLED is set. A production
  install turns it on; a developer gets the report and decides.

* **Never touch anything reachable.** A discovered job that was imported into
  the assistant, a form-field schema for an application that has not reached a
  terminal state, a run that is still active - all are excluded regardless of
  age. Age alone is not sufficient grounds for deletion when the row might still
  be the thing a user is looking at.

SQLite keeps freed pages for reuse rather than returning them to the
filesystem, so the sweep finishes with an incremental vacuum. Without it the
file only ever grows, however much is deleted.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.store import EntityStore, session_scope

logger = logging.getLogger("career_os.retention")


def _days(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


# Per-table windows. Generous by default: the point is to stop unbounded growth,
# not to aggressively reclaim space.
DISCOVERED_JOB_DAYS = _days("CAREEROS_RETAIN_DISCOVERED_DAYS", 90)
FORM_FIELD_DAYS = _days("CAREEROS_RETAIN_FORM_FIELD_DAYS", 60)
RUN_DAYS = _days("CAREEROS_RETAIN_RUN_DAYS", 45)
USAGE_EVENT_DAYS = _days("CAREEROS_RETAIN_USAGE_EVENT_DAYS", 30)

# Statuses that mean an application is finished with, so its captured form
# schema is no longer needed to resume or retry it.
_TERMINAL_APPLICATION_STATUSES = ("SUBMITTED", "INELIGIBLE", "SKIPPED")


@dataclass
class SweepReport:
    """What the sweep removed, or would remove in dry-run mode."""

    dry_run: bool = True
    removed: dict[str, int] = field(default_factory=dict)
    bytes_before: int = 0
    bytes_after: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.removed.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "dryRun": self.dry_run,
            "removed": dict(self.removed),
            "totalRows": self.total,
            "bytesBefore": self.bytes_before,
            "bytesAfter": self.bytes_after,
            "errors": list(self.errors),
        }


def _cutoff_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _json(path: str):
    return func.json_extract(EntityStore.payload, path)


def _aged_out(cutoff: str, *paths: str):
    """Rows whose newest known timestamp is older than `cutoff`.

    A row with no usable timestamp is KEPT. The obvious spelling -
    coalesce(ts, '') < cutoff - is wrong in exactly the dangerous direction: an
    empty string sorts before every date, so every row missing a timestamp reads
    as ancient. A first draft of this sweep matched 7,044 of 7,076 discovered
    jobs for that reason. Absence of evidence is not grounds for deletion.
    """
    newest = func.coalesce(*[_json(p) for p in paths])
    return [newest.isnot(None), newest != "", newest < cutoff]


def _count_then_maybe_delete(
    db: Session, report: SweepReport, label: str, query
) -> None:
    """Count matching rows, and delete them unless this is a dry run."""
    try:
        matched = query.count()
        report.removed[label] = matched
        if matched and not report.dry_run:
            query.delete(synchronize_session=False)
    except Exception as exc:  # noqa: BLE001 - one table must not abort the sweep
        report.errors.append(f"{label}: {type(exc).__name__}: {exc}")
        logger.exception("Retention sweep failed for %s", label)


def _terminal_application_ids(db: Session) -> set[str]:
    rows = (
        db.query(EntityStore.id)
        .filter(EntityStore.entity_type == "aa_autopilot_job")
        .filter(_json("$.status").in_(_TERMINAL_APPLICATION_STATUSES))
        .all()
    )
    return {row[0] for row in rows}


def sweep(dry_run: bool | None = None) -> SweepReport:
    """Apply every retention policy once. Safe to call repeatedly."""
    if dry_run is None:
        enabled = os.environ.get("CAREEROS_RETENTION_ENABLED", "").strip().lower()
        dry_run = enabled not in ("1", "true", "yes", "on")

    report = SweepReport(dry_run=dry_run)

    with session_scope() as db:
        try:
            report.bytes_before = int(
                db.execute(text("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")).scalar()
                or 0
            )
        except Exception:
            report.bytes_before = 0

        # Discovered jobs that were never pulled into the assistant. A job the
        # user imported has a real application attached and is never swept.
        discovered = (
            db.query(EntityStore)
            .filter(EntityStore.entity_type == "aa_discovered_job")
            .filter(
                *_aged_out(
                    _cutoff_iso(DISCOVERED_JOB_DAYS),
                    "$.lastSeenDate",
                    "$.firstSeenDate",
                    "$.scrapedAt",
                )
            )
            .filter(func.coalesce(_json("$.addedToAssistant"), 0) == 0)
        )
        _count_then_maybe_delete(db, report, "aa_discovered_job", discovered)

        # Form-field schemas belonging to applications that are finished with.
        terminal_ids = _terminal_application_ids(db)
        if terminal_ids:
            form_fields = (
                db.query(EntityStore)
                .filter(EntityStore.entity_type == "aa_form_field")
                .filter(_json("$.applicationId").in_(tuple(terminal_ids)))
                # Age on capture time, not updatedAt. upsert_entity rewrites
                # updatedAt on every save, so a row touched for any unrelated
                # reason would reset its retention clock and never age out.
                .filter(*_aged_out(_cutoff_iso(FORM_FIELD_DAYS), "$.discoveredAt", "$.createdAt"))
            )
            _count_then_maybe_delete(db, report, "aa_form_field", form_fields)
        else:
            report.removed["aa_form_field"] = 0

        # Completed run records. An active run has no completedAt yet, so the
        # coalesce keeps it out of range rather than relying on status strings.
        runs = (
            db.query(EntityStore)
            .filter(EntityStore.entity_type == "aa_autopilot_run")
            .filter(*_aged_out(_cutoff_iso(RUN_DAYS), "$.completedAt", "$.stoppedAt"))
        )
        _count_then_maybe_delete(db, report, "aa_autopilot_run", runs)

        # Telemetry. Pure history, safe to age out soonest.
        usage = (
            db.query(EntityStore)
            .filter(EntityStore.entity_type == "model_usage_event")
            .filter(*_aged_out(_cutoff_iso(USAGE_EVENT_DAYS), "$.timestamp", "$.createdAt"))
        )
        _count_then_maybe_delete(db, report, "model_usage_event", usage)

    if not dry_run and report.total:
        reclaim_space()

    with session_scope() as db:
        try:
            report.bytes_after = int(
                db.execute(text("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")).scalar()
                or 0
            )
        except Exception:
            report.bytes_after = report.bytes_before

    logger.info(
        "Retention sweep (%s): %s",
        "dry run" if dry_run else "applied",
        report.to_dict(),
    )
    return report


def reclaim_space(pages: int = 2000) -> None:
    """Return freed pages to the filesystem.

    auto_vacuum=INCREMENTAL only marks pages reusable; this hands them back.
    Bounded per call so a sweep never blocks the database for long.
    """
    try:
        with session_scope() as db:
            db.execute(text(f"PRAGMA incremental_vacuum({pages})"))
    except Exception:
        logger.exception("Incremental vacuum failed")
