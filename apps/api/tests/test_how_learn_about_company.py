"""Regression: "How did you learn about <Company>?" is a how-heard question.

Seen live on Traversal (Ashby, 2026-11-05): the resolver returned UNKNOWN,
the required field stayed empty and the job went to review.
"""
from __future__ import annotations

import pytest

from app.services.application_assistant.answer_classification import resolve_answer

PROFILE = {"jobDiscoveryDefault": "Company careers page"}


@pytest.mark.parametrize("label", [
    "How Did You Learn About Traversal?",
    "How did you learn about us?",
    "How did you learn about this position?",
])
def test_learn_about_company_is_how_heard(label):
    r = resolve_answer(question_text=label, profile=PROFILE, options=None)
    assert r.question_type == "HOW_HEARD"
    assert r.answer == "Company careers page"


def test_learn_about_tech_is_not_how_heard():
    r = resolve_answer(question_text="What did you learn about distributed systems in your last role?",
                       profile=PROFILE, options=None)
    assert r.question_type != "HOW_HEARD"
