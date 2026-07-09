"""Gmail IMAP helpers for recruiter thread discovery — migrated from Arsenal scripts/email."""

from __future__ import annotations

import email
import imaplib
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any


RECRUITER_SEARCH_TERMS = ("recruiter", "hiring", "interview", "application")


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _parse_address_list(header_value: str | None) -> tuple[str, str]:
    if not header_value:
        return "", ""
    parsed = email.utils.parseaddr(header_value)
    return parsed[0] or "", parsed[1] or ""


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
            status, _ = client.select(mailbox, readonly=True)
            if status == "OK":
                return mailbox
        raise RuntimeError("Unable to open Gmail mailbox.")

    def search_recruiter_uids(self, limit: int = 150) -> list[str]:
        client = self._connect()
        try:
            self._open_mailbox(client)
            uid_set: set[str] = set()
            for term in RECRUITER_SEARCH_TERMS:
                status, data = client.uid("search", None, f'(SUBJECT "{term}")')
                if status == "OK" and data and data[0]:
                    uid_set.update(data[0].decode().split())
            ordered = sorted(uid_set, key=int)
            return ordered[-limit:][::-1]
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def fetch_threads(self, limit: int = 10) -> list[dict[str, Any]]:
        uids = self.search_recruiter_uids(limit=limit)
        if not uids:
            return []

        client = self._connect()
        try:
            self._open_mailbox(client)
            threads: list[dict[str, Any]] = []
            for uid in uids:
                status, data = client.uid("fetch", uid, "(RFC822.HEADER)")
                if status != "OK" or not data or not data[0]:
                    continue
                raw = data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                msg = email.message_from_bytes(raw)
                from_name, from_address = _parse_address_list(msg.get("From"))
                date_raw = msg.get("Date")
                try:
                    date_value = parsedate_to_datetime(date_raw).isoformat() if date_raw else datetime.utcnow().isoformat()
                except (TypeError, ValueError, OverflowError):
                    date_value = datetime.utcnow().isoformat()
                threads.append(
                    {
                        "uid": uid,
                        "subject": _decode_header_value(msg.get("Subject")) or "No Subject",
                        "fromName": from_name,
                        "fromAddress": from_address,
                        "date": date_value,
                    }
                )
            return threads
        finally:
            try:
                client.logout()
            except Exception:
                pass
