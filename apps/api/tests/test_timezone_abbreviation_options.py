"""Regression: "Which timezone are you currently located in?" offering PST/MST/CST/EST.

Seen live on Lever (Veeva, 2026-11-05): the candidate is in Pacific Time but the
options were bare abbreviations, none matched "Pacific Time (PT)", and the
required field went to review.
"""
from app.services.application_assistant.profile_answer_resolver import resolve_answer

_Q = "Which timezone are you currently located in?"


def test_pacific_candidate_picks_pst():
    r = resolve_answer(question_text=_Q, profile={"state": "Washington"}, options=["PST", "MST", "CST", "EST"])
    assert r.answer == "PST"


def test_eastern_candidate_picks_est_or_et():
    assert resolve_answer(question_text=_Q, profile={"state": "New York"}, options=["PT", "MT", "CT", "ET"]).answer == "ET"
    assert resolve_answer(question_text=_Q, profile={"state": "NY"}, options=["PST", "EST"]).answer == "EST"


def test_no_matching_zone_still_blocks():
    r = resolve_answer(question_text=_Q, profile={"state": "Washington"}, options=["CST", "EST"])
    assert r.answer is None and r.blocking_errors
