"""Gmail IMAP helpers for recruiter thread discovery — migrated from Arsenal scripts/email."""

from __future__ import annotations

import email
import imaplib
import logging
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any

RECRUITER_SEARCH_TERMS = ("recruiter", "hiring", "interview", "application")


logger = logging.getLogger("career_os.gmail_imap")


def _decode_header_value(value: str | None) -> str:
    """Decode an RFC 2047 header, whatever charset it claims.

    `errors="replace"` does not save a bad charset name: the codec lookup
    happens first and raises LookupError before any byte is decoded. Headers
    routinely carry names Python has no codec for - "unknown-8bit" is a
    standard placeholder (RFC 1428) meaning the sender did not know either -
    and the exception propagated far enough to abort a whole fetch batch. In a
    2,267-message sync that cost 800 messages.

    So: try what the header claims, then fall back. latin-1 never fails, which
    guarantees a usable subject line rather than a lost message.
    """
    if not value:
        return ""
    parts: list[str] = []
    for chunk, encoding in decode_header(value):
        if not isinstance(chunk, bytes):
            parts.append(str(chunk))
            continue
        for candidate in (encoding, "utf-8", "latin-1"):
            if not candidate:
                continue
            try:
                parts.append(chunk.decode(candidate, errors="replace"))
                break
            except (LookupError, UnicodeDecodeError):
                continue
        else:
            parts.append(chunk.decode("ascii", errors="replace"))
    return "".join(parts)


def _parse_address_list(header_value: str | None) -> tuple[str, str]:
    if not header_value:
        return "", ""
    parsed = email.utils.parseaddr(header_value)
    return parsed[0] or "", parsed[1] or ""


def _extract_snippet(msg: email.message.Message, max_chars: int = 500) -> str:
    """Best-effort plain-text snippet from a parsed email, for classification only."""
    text = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and not part.get_filename():
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="replace")
                        break
        elif msg.get_content_type() == "text/plain":
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
    except Exception:
        text = ""
    cleaned = " ".join(text.split())
    return cleaned[:max_chars]


class GmailImapClient:
    def __init__(self, user: str, app_password: str) -> None:
        if not user or not app_password:
            raise ValueError("Gmail credentials (user, app_password) are required.")
        self.user = user
        self.app_password = app_password

    def _connect(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL("imap.gmail.com")
        client.login(self.user, self.app_password)
        return client

    def _open_mailbox(self, client: imaplib.IMAP4_SSL) -> str:
        for mailbox in ("[Gmail]/All Mail", "INBOX"):
            try:
                # Mailbox names containing spaces/brackets must be quoted or
                # Gmail's IMAP server rejects the SELECT/EXAMINE command outright
                # (raises imaplib.IMAP4.error rather than returning a bad status).
                status, _ = client.select(f'"{mailbox}"', readonly=True)
            except imaplib.IMAP4.error:
                continue
            if status == "OK":
                return mailbox
        raise RuntimeError("Unable to open Gmail mailbox.")

    def search_uids_by_recipient(self, address: str, limit: int = 20) -> list[str]:
        """Exact IMAP TO-search for one address — used to confirm a specific
        application's tracking-tagged submission actually landed a reply."""
        client = self._connect()
        try:
            self._open_mailbox(client)
            try:
                status, data = client.uid("search", None, f'(TO "{address}")')
            except Exception:
                return []
            if status != "OK" or not data or not data[0]:
                return []
            uids = sorted(data[0].decode().split(), key=int)
            return uids[-limit:][::-1]
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def search_recruiter_uids(self, limit: int = 150) -> list[str]:
        client = self._connect()
        try:
            self._open_mailbox(client)
            uid_set: set[str] = set()

            # 1. Primary: All emails delivered to the CareerOS alias
            for to_query in ('(TO "careeros")', '(TO "amsborse+careeros@gmail.com")'):
                try:
                    status, data = client.uid("search", None, to_query)
                    if status == "OK" and data and data[0]:
                        uid_set.update(data[0].decode().split())
                except Exception:
                    pass

            # 2. ATS and Job Platform senders & subject keywords
            search_queries = [
                '(FROM "greenhouse")',
                '(FROM "greenhouse-mail")',
                '(FROM "lever")',
                '(FROM "ashby")',
                '(FROM "workday")',
                '(FROM "smartrecruiters")',
                '(SUBJECT "Security code")',
                '(SUBJECT "application")',
                '(SUBJECT "interview")',
                '(SUBJECT "recruiter")',
                '(SUBJECT "hiring")',
                '(SUBJECT "offer")',
            ]
            for q in search_queries:
                try:
                    status, data = client.uid("search", None, q)
                    if status == "OK" and data and data[0]:
                        uid_set.update(data[0].decode().split())
                except Exception:
                    pass

            ordered = sorted(uid_set, key=int)
            return ordered[-limit:][::-1]
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def fetch_threads(self, limit: int = 10, include_body: bool = False) -> list[dict[str, Any]]:
        """Fetch recruiter threads. Batch fetches messages in a single IMAP round trip
        for instant loading and attaches categorized snippets."""
        uids = self.search_recruiter_uids(limit=limit)
        return self._fetch_uids(uids, include_body=include_body)

    def fetch_by_recipient(self, address: str, limit: int = 20, include_body: bool = True) -> list[dict[str, Any]]:
        """All messages delivered to one exact tracking address (submission-confirmation lookup)."""
        uids = self.search_uids_by_recipient(address, limit=limit)
        return self._fetch_uids(uids, include_body=include_body)

    def _fetch_uids(self, uids: list[str], include_body: bool = False) -> list[dict[str, Any]]:
        import re

        if not uids:
            return []

        client = self._connect()
        try:
            self._open_mailbox(client)
            threads: list[dict[str, Any]] = []
            fetch_spec = "(RFC822 UID)" if include_body else "(RFC822.HEADER UID)"

            # Batch fetch all UIDs in one single IMAP round-trip
            uids_str = ",".join(uids)
            status, data = client.uid("fetch", uids_str, fetch_spec)
            if status == "OK" and data:
                for item in data:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue
                    raw = item[1]
                    if not isinstance(raw, (bytes, bytearray)):
                        continue
                    # A message that will not parse must cost only itself.
                    # Fetches run in batches of up to 200 UIDs, so an exception
                    # escaping this loop discarded the 199 good messages
                    # alongside it - measured, that lost 800 of 2,267 messages
                    # in a full mailbox sync.
                    try:
                        header_str = item[0].decode(errors="replace") if isinstance(item[0], bytes) else str(item[0])
                        uid_match = re.search(r"UID\s+(\d+)", header_str)
                        item_uid = uid_match.group(1) if uid_match else ""

                        msg = email.message_from_bytes(raw)
                        from_name, from_address = _parse_address_list(msg.get("From"))
                        date_raw = msg.get("Date")
                        try:
                            date_value = parsedate_to_datetime(date_raw).isoformat() if date_raw else datetime.utcnow().isoformat()
                        except (TypeError, ValueError, OverflowError):
                            date_value = datetime.utcnow().isoformat()
                        to_raw = msg.get("Delivered-To") or msg.get("X-Original-To") or msg.get("To") or ""
                        entry: dict[str, Any] = {
                            "uid": item_uid or str(len(threads)),
                            "subject": _decode_header_value(msg.get("Subject")) or "No Subject",
                            "fromName": from_name,
                            "fromAddress": from_address,
                            "toAddress": _decode_header_value(to_raw).strip().lower(),
                            "date": date_value,
                        }
                        if include_body:
                            entry["snippet"] = _extract_snippet(msg)
                    except Exception:  # noqa: BLE001
                        logger.debug("skipping unparseable message", exc_info=True)
                        continue
                    threads.append(entry)

            threads.sort(key=lambda item: item.get("date") or "", reverse=True)
            return threads
        finally:
            try:
                client.logout()
            except Exception:
                pass
