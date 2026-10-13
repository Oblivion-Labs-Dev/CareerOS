"""Roblox postings are hand-apply jobs, and every layer says so consistently.

careers.roblox.com refuses every automated browser at the network edge
(connection reset or HTTP/2 protocol error, verified 2026-09-15), while curl
and a person's Chrome load it. The hard filter keeps Roblox out of the
automation, and its reason has to be recognised as bot protection by the
ineligibility classifier and the Diagnostic page; a reason neither recognises
sends every queued Roblox job through a ~9-minute browser attempt.
"""

import pytest

from app.services.application_assistant.domain import IneligibilityReason
from app.services.application_assistant.ineligibility import _first_text_match
from app.services.application_assistant.job_filter_ranker import evaluate_hard_filters
from app.services.diagnostic_outcomes import reason_category

PREVIOUS_REASON = (
    "Roblox's Greenhouse-hosted apply form reliably times out in CareerOS's automation "
    "(verified live 2026-09-14); a manual browser hit no challenge on a current posting, "
    "so this is unconfirmed as an actual bot-wall - see NIGHT_BATCH_DECISIONS.md"
)


def _roblox_reason(url: str) -> str:
    job = {"company": "Roblox", "title": "Senior Software Engineer", "applicationUrl": url}
    passed, reason = evaluate_hard_filters(job, {}, [], {"allowDuplicates": True})
    assert not passed
    return reason


@pytest.mark.parametrize(
    "url",
    [
        "https://careers.roblox.com/jobs/7012345",
        # Formerly exempted as a one-off live test; the test is long finished.
        "https://careers.roblox.com/jobs/8127056",
        "https://job-boards.greenhouse.io/roblox/jobs/7012345",
    ],
)
def test_every_roblox_posting_is_filtered(url):
    reason = _roblox_reason(url)
    assert "refuses automated browsers" in reason
    assert "unconfirmed" not in reason


def test_reason_is_classified_as_bot_protection():
    reason = _roblox_reason("https://careers.roblox.com/jobs/7012345")
    assert _first_text_match(reason) is IneligibilityReason.BOT_PROTECTED_BOARD


def test_previous_wording_on_existing_rows_is_still_bot_protection():
    assert _first_text_match(PREVIOUS_REASON) is IneligibilityReason.BOT_PROTECTED_BOARD


ROBLOX_CATEGORY = "Roblox refuses automated browsers (apply by hand)"


def test_diagnostic_page_groups_the_reason():
    reason = _roblox_reason("https://careers.roblox.com/jobs/7012345")
    assert reason_category({"lastError": reason}) == ROBLOX_CATEGORY


def test_diagnostic_page_groups_the_previous_wording():
    assert reason_category({"lastError": PREVIOUS_REASON}) == ROBLOX_CATEGORY
