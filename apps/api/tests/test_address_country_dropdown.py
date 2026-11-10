"""Regression: a dropdown labelled "Address" that lists countries gets the country.

Seen live on Greenhouse (Cloudbeds, 2026-11-05): required "Address*" was a
54-option country select; the resolver answered the street line, which matched
no option, so the field stayed empty and the job went to review.
"""
from app.services.application_assistant.profile_answer_resolver import resolve_answer

PROFILE = {"streetAddress": "1 Main St", "city": "Seattle", "state": "Washington", "zip": "98101", "country": "United States"}
COUNTRIES = ["Argentina", "Austria", "Australia", "Brazil", "Canada", "United Kingdom", "United States"]


def test_address_country_dropdown_answers_country():
    r = resolve_answer(question_text="Address*", profile=PROFILE, options=COUNTRIES)
    assert r.answer == "United States"


def test_plain_address_text_box_keeps_street():
    r = resolve_answer(question_text="Address", profile=PROFILE, options=None)
    assert r.answer == "1 Main St"
