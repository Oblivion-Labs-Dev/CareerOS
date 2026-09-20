"""Lever fronts its checkbox/radio inputs with an hCaptcha widget that a
genuine click can trigger mid-form, blocking every field after it. The
executor checks `_is_lever_board` before falling back to a click so it never
risks that on a Lever posting.
"""

from __future__ import annotations

from app.services.application_assistant.playwright_autopilot_executor import _is_lever_board


class _FakePage:
    def __init__(self, url: str):
        self.url = url


def test_a_lever_hosted_url_is_detected():
    assert _is_lever_board(_FakePage("https://jobs.lever.co/acme/1234-5678/apply")) is True


def test_case_is_ignored():
    assert _is_lever_board(_FakePage("HTTPS://JOBS.LEVER.CO/acme/apply")) is True


def test_other_boards_are_not_lever():
    assert _is_lever_board(_FakePage("https://job-boards.greenhouse.io/acme/jobs/1")) is False
    assert _is_lever_board(_FakePage("https://jobs.ashbyhq.com/acme/abc")) is False
    assert _is_lever_board(_FakePage("https://acme.wd1.myworkdayjobs.com/careers")) is False


def test_a_missing_or_empty_url_is_not_lever():
    assert _is_lever_board(_FakePage("")) is False
    assert _is_lever_board(_FakePage(None)) is False
