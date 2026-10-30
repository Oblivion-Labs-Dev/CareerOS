"""A human-or-bot screening question is answered with the human option.

A Greenhouse form asks "Which of the following best describes you?"
with "I am an AI, bot or Automated Program." / "I am a human." The resolver had
no rule for it, so the required field stayed blank and three applications were
staged for review. The owner approved answering it for themselves (2026-10-30).
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

OPTIONS = ["I am an AI, bot or Automated Program.", "I am a human."]


def test_human_check_picks_the_human_option():
    res = resolve_answer("Which of the following best describes you?", {}, options=OPTIONS)
    assert res.answer == "I am a human."


def test_same_wording_without_a_bot_option_is_not_touched():
    hybrid = ["I can meet the hybrid requirement", "I cannot meet the hybrid requirement"]
    res = resolve_answer("Which of the following best describes you?", {}, options=hybrid)
    assert res.answer != "I am a human."
