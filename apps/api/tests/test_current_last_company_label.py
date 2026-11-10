"""Regression: Ashby's "Current/Last Company" label must resolve to the current employer.

Seen live on Plaid (2026-11-05): the resolver returned UNKNOWN for
"Current/Last Company", the required field stayed empty and the job went to
review even though the profile has a current company.
"""
from __future__ import annotations

import pytest

from app.services.application_assistant.answer_classification import resolve_answer

PROFILE = {"currentCompany": "Microsoft", "fullName": "Test Person"}


@pytest.mark.parametrize("label", [
    "Current/Last Company",
    "Current / Last Company*",
    "Current/Previous Company",
    "Last Company",
    "Most Recent Employer",
])
def test_current_or_last_company_resolves(label):
    r = resolve_answer(question_text=label, profile=PROFILE, options=None)
    assert r.question_type == "CURRENT_COMPANY"
    assert r.answer == "Microsoft"


def test_previous_employment_yes_no_is_not_a_company_name():
    r = resolve_answer(question_text="Have you previously worked at Plaid?", profile=PROFILE,
                       options=["Yes", "No"])
    assert r.question_type != "CURRENT_COMPANY"
