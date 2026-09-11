"""Sync the whole application mailbox into the database, once.

The existing paths cap what they fetch - `search_recruiter_uids` keeps the
newest 150 UIDs, the inbox endpoint accepts at most 100 - and then re-download
those same messages from IMAP on every request. With 188 submitted applications
plus their confirmation codes, rejections and follow-ups, the newest 100
messages do not reach back far enough to cover the account, so older
correspondence was invisible no matter how often the sync ran.

This module fixes both halves:

* **Everything, not a page.** Every matching UID is fetched, in batches, with no
  ceiling. A first run over a few thousand messages takes a while; it happens
  once.
* **Fetched once, kept forever.** Each message is stored as an entity keyed by
  its IMAP UID, and a watermark records the highest UID already seen. Later
  syncs ask the server only for `UID <watermark+1>:*`, so a routine sync
  transfers the handful of messages that arrived since.

The watermark is only sound while UIDs mean what they meant last time, so
UIDVALIDITY is stored alongside it. Gmail changes that value if the mailbox is
recreated, and every stored UID becomes meaningless at that moment - so a change
forces a full resync rather than silently syncing against stale numbers.
"""

from __future__ import annotations

import imaplib
import logging
import time
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import get_kv, list_entities, set_kv, upsert_entity
from app.services.gmail_imap import GmailImapClient

logger = logging.getLogger("career_os.gmail_archive")

ENTITY_TYPE = "email_message"
STATE_KEY = "gmail_archive_state"

#: How many UIDs to FETCH per round trip. Gmail tolerates large batches, but a
#: failure mid-batch costs the whole batch, and progress is saved per batch - so
#: this trades a little throughput for not losing ten minutes of work.
BATCH_SIZE = 200

#: Searches that define "mail about my applications". Deliberately broad: it is
#: cheaper to store a message that turns out to be irrelevant than to discover
#: months later that the filter excluded the one confirmation that mattered.
SEARCH_TERMS = (
    '(TO "careeros")',
    '(SUBJECT "application")',
    '(SUBJECT "applying")',
    '(SUBJECT "your application")',
    '(SUBJECT "thank you for applying")',
    '(SUBJECT "we received")',
    '(SUBJECT "interview")',
    '(SUBJECT "assessment")',
    '(SUBJECT "verification")',
    '(SUBJECT "confirm")',
    '(SUBJECT "unfortunately")',
    '(SUBJECT "regret")',
    '(SUBJECT "not moving forward")',
    '(SUBJECT "offer")',
    '(SUBJECT "recruiter")',
    '(SUBJECT "position")',
    '(SUBJECT "role")',
)


@dataclass
class SyncReport:
    stored: int = 0
    skipped_existing: int = 0
    matched: int = 0
    batches: int = 0
    full_resync: bool = False
    uid_validity: str = ""
    highest_uid: int = 0
    since_date: str = ""
    newest_message_date: str = ""
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": not self.errors or self.stored > 0,
            "stored": self.stored,
            "skippedExisting": self.skipped_existing,
            "matched": self.matched,
            "batches": self.batches,
            "fullResync": self.full_resync,
            "uidValidity": self.uid_validity,
            "highestUid": self.highest_uid,
            "sinceDate": self.since_date,
            "newestMessageDate": self.newest_message_date,
            "seconds": round(self.seconds, 1),
            "errors": self.errors[:5],
        }


def load_state(db: Session) -> dict[str, Any]:
    return get_kv(db, STATE_KEY) or {}


def _uid_validity(client: imaplib.IMAP4_SSL) -> str:
    """The mailbox generation. Stored UIDs only mean something within one."""
    try:
        status, data = client.status('"[Gmail]/All Mail"', "(UIDVALIDITY)")
        if status == "OK" and data:
            text = data[0].decode()
            if "UIDVALIDITY" in text:
                return text.split("UIDVALIDITY")[1].strip(" ()\r\n")
    except Exception:
        pass
    return ""


#: How far before the last-seen message date to re-scan. IMAP SINCE is
#: date-granular and compares against the server's internal date, which can sit
#: a day either side of the Date: header once timezones are involved, so an
#: exact boundary would silently drop messages that arrived around it. Two days
#: of overlap costs a few already-stored UIDs, which are skipped anyway.
SINCE_SAFETY_DAYS = 2


def _imap_date(value: str) -> str | None:
    """An ISO timestamp as IMAP's dd-Mon-yyyy, minus the safety margin."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed - timedelta(days=SINCE_SAFETY_DAYS)).strftime("%d-%b-%Y")


def _search_all(
    client: imaplib.IMAP4_SSL,
    since_uid: int,
    since_date: str | None = None,
) -> set[str]:
    """Every UID matching any search term, narrowed by UID and/or date.

    Two independent watermarks, because they fail in different situations:

    * **UID range** (`UID 4001:*`) is exact and cheap, and is the primary
      mechanism. It is only meaningful while UIDVALIDITY is unchanged.
    * **SINCE date** survives a UIDVALIDITY change, which resets the UID space
      and would otherwise force re-reading the entire mailbox from the
      beginning. It is coarse - IMAP compares whole days - so it is a bound,
      not a precise cursor.

    Using both means a routine sync is exact, and the rare mailbox reset costs
    a scan back to the last known message date rather than to the first message
    ever received.
    """
    found: set[str] = set()
    clauses = []
    if since_uid:
        clauses.append(f"UID {since_uid + 1}:*")
    if since_date:
        clauses.append(f"SINCE {since_date}")
    scope = " ".join(clauses)

    for term in SEARCH_TERMS:
        query = f"({scope} {term})" if scope else term
        try:
            status, data = client.uid("search", None, query)
        except Exception as exc:  # noqa: BLE001
            logger.debug("search failed for %s: %s", term, exc)
            continue
        if status == "OK" and data and data[0]:
            found.update(data[0].decode().split())
    return found


def sync_archive(
    db: Session,
    *,
    force_full: bool = False,
    from_beginning: bool = False,
    max_messages: int | None = None,
) -> SyncReport:
    """Fetch every application-related message not already stored.

    Incremental by default. `force_full` re-scans the whole mailbox, which is
    still cheap in transfer terms because anything already stored is skipped
    before its body is fetched.
    """
    from app.config import settings

    report = SyncReport()
    started = time.perf_counter()

    if not settings.gmail_user or not settings.gmail_app_password:
        report.errors.append("Gmail is not configured")
        return report

    state = load_state(db)
    client = GmailImapClient(settings.gmail_user, settings.gmail_app_password)

    try:
        connection = client._connect()  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"IMAP login failed: {exc}")
        return report

    try:
        client._open_mailbox(connection)  # noqa: SLF001
        report.uid_validity = _uid_validity(connection)

        stored_validity = str(state.get("uidValidity") or "")
        if stored_validity and report.uid_validity and stored_validity != report.uid_validity:
            # Every stored UID now refers to a different message, or to none.
            logger.warning(
                "Gmail UIDVALIDITY changed (%s -> %s); re-scanning from the start",
                stored_validity, report.uid_validity,
            )
            force_full = True

        since = 0 if force_full else int(state.get("highestUid") or 0)
        # The date bound still applies on a forced rescan and after a
        # UIDVALIDITY reset - that is the case it exists for. Only an explicit
        # request for the whole history drops it.
        since_date = None if from_beginning else _imap_date(
            str(state.get("newestMessageDate") or state.get("lastSyncAt") or "")
        )
        report.since_date = since_date or ""
        report.full_resync = since == 0
        uids = _search_all(connection, since, since_date)
        report.matched = len(uids)
    finally:
        try:
            connection.logout()
        except Exception:
            pass

    if not uids:
        report.seconds = time.perf_counter() - started
        _save_state(db, state, report)
        return report

    known = {str(e.get("uid")) for e in list_entities(db, ENTITY_TYPE)}
    pending = sorted((u for u in uids if u not in known), key=int)
    report.skipped_existing = len(uids) - len(pending)
    if max_messages:
        pending = pending[-max_messages:]

    highest = int(state.get("highestUid") or 0)
    # The newest message *date*, not the sync time: what matters for a later
    # SINCE search is how recent the mail is, and a sync that finds nothing
    # must not advance the window past mail it never saw.
    newest_date = str(state.get("newestMessageDate") or "")

    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        try:
            messages = client._fetch_uids(batch, include_body=True)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"batch at {start}: {type(exc).__name__}: {exc}"[:160])
            continue
        report.batches += 1

        for message in messages:
            uid = str(message.get("uid") or "")
            if not uid:
                continue
            upsert_entity(db, ENTITY_TYPE, {
                "id": f"email_{uid}",
                "uid": uid,
                "subject": message.get("subject"),
                "fromName": message.get("fromName"),
                "fromAddress": message.get("fromAddress"),
                "toAddress": message.get("toAddress"),
                "date": message.get("date"),
                # The IMAP client extracts a ~500 character snippet rather than
                # a full body, so that is what is stored. Storing a "body" key
                # holding a snippet would mislead every later reader into
                # thinking the whole message was available.
                "snippet": message.get("snippet"),
                "uidValidity": report.uid_validity,
                "syncedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            report.stored += 1
            highest = max(highest, int(uid))
            stamp = str(message.get("date") or "")
            if stamp > newest_date:
                newest_date = stamp

        # Persist the watermark per batch, so an interrupted sync resumes rather
        # than starting over - the failure mode that makes people avoid running
        # a long sync at all.
        state = {**state, "highestUid": highest, "uidValidity": report.uid_validity,
                 "newestMessageDate": newest_date}
        set_kv(db, STATE_KEY, {**state, "lastSyncAt": time.strftime("%Y-%m-%dT%H:%M:%S")})
        logger.info("Gmail archive: %d/%d stored", report.stored, len(pending))

    report.highest_uid = highest
    report.newest_message_date = newest_date
    report.seconds = time.perf_counter() - started
    _save_state(db, state, report)
    return report


def _save_state(db: Session, state: dict[str, Any], report: SyncReport) -> None:
    set_kv(db, STATE_KEY, {
        **state,
        "highestUid": report.highest_uid or state.get("highestUid") or 0,
        "uidValidity": report.uid_validity or state.get("uidValidity") or "",
        "newestMessageDate": report.newest_message_date or state.get("newestMessageDate") or "",
        "lastSyncAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "totalStored": _count(db),
    })


def _count(db: Session) -> int:
    try:
        return len(list_entities(db, ENTITY_TYPE))
    except Exception:
        return 0


def read_archive(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    query: str = "",
) -> dict[str, Any]:
    """Serve the inbox from the database. No IMAP connection is opened.

    This is the half that makes the sync worth doing: the inbox used to
    re-download messages from Gmail on every page view.
    """
    messages = list_entities(db, ENTITY_TYPE)
    if query:
        needle = query.lower()
        messages = [
            m for m in messages
            if needle in str(m.get("subject", "")).lower()
            or needle in str(m.get("fromName", "")).lower()
            or needle in str(m.get("fromAddress", "")).lower()
            or needle in str(m.get("snippet", "")).lower()
        ]
    messages.sort(key=lambda m: int(m.get("uid") or 0), reverse=True)
    window = messages[offset : offset + limit]
    return {
        "total": len(messages),
        "offset": offset,
        "limit": limit,
        "messages": window,
        "state": load_state(db),
    }
