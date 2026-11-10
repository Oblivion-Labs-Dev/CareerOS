"""Regression: a rejected Gmail app password must fail loudly and fast.

Seen live 2026-11-05 (xAI on Greenhouse): apps/api/.env still held a revoked
app password, IMAP answered AUTHENTICATIONFAILED on every poll, and the poller
logged that at DEBUG and kept retrying for the full 150s. The application
ended SUBMISSION_UNKNOWN with only "timed out" in the log, which looked like a
slow email rather than a credentials problem.
"""
from __future__ import annotations

import asyncio
import imaplib
import logging
import time

from app.services.application_assistant import greenhouse_verification_service as g


class _RejectingIMAP:
    logins = 0

    def __init__(self, *a, **k):
        pass

    def login(self, user, pw):
        _RejectingIMAP.logins += 1
        raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")

    def logout(self):
        pass


def test_auth_failure_stops_polling_and_logs_error(monkeypatch, caplog):
    _RejectingIMAP.logins = 0
    monkeypatch.setattr(g.imaplib, "IMAP4_SSL", _RejectingIMAP)
    monkeypatch.setenv("GMAIL_USER", "someone@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "wrong")
    messages: list[tuple[str, str]] = []

    started = time.time()
    with caplog.at_level(logging.ERROR, logger="career_os.greenhouse_verification"):
        code = asyncio.run(
            g.fetch_latest_greenhouse_verification_code(
                "Xai", time.time(), timeout_sec=5, poll_interval=0.01,
                log_callback=lambda m, lvl: messages.append((lvl, m)),
            )
        )

    assert code is None
    assert time.time() - started < 2, "must not keep retrying a rejected password"
    assert _RejectingIMAP.logins == 1
    assert any("GMAIL_APP_PASSWORD" in r.getMessage() for r in caplog.records)
    assert any(lvl == "error" and "GMAIL_APP_PASSWORD" in m for lvl, m in messages)
