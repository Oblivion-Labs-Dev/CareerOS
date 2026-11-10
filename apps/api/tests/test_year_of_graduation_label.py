"""Regression: "Year Of Graduation" is the education end year.

Seen live on Pear VC (Ashby, 2026-11-05): the resolver only knew
"Graduation Year", so the required field stayed empty and the job went to review.
"""
from __future__ import annotations

import pytest

from app.services.application_assistant.answer_classification import resolve_answer

PROFILE = {"education": [
    {"school": "Santa Clara University", "degree": "Master's Degree", "endDate": "06/2019"},
    {"school": "PICT", "degree": "Bachelor's Degree", "endDate": "06/2016"},
]}


@pytest.mark.parametrize("label", [
    "Year Of Graduation",
    "Year of graduation*",
    "What year did you graduate?",
    "Graduation Year",
])
def test_year_of_graduation_resolves(label):
    r = resolve_answer(question_text=label, profile=PROFILE, options=None)
    assert r.question_type == "EDUCATION_END_YEAR"
    assert str(r.answer) == "2019"


def test_expected_graduation_date_for_students_is_not_end_year_text():
    r = resolve_answer(question_text="Are you a recent graduate?", profile=PROFILE, options=["Yes", "No"])
    assert r.question_type != "EDUCATION_END_YEAR"
