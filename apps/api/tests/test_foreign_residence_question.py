"""Residence in a foreign jurisdiction is answered from the profile's country.

Flexport's Greenhouse form asks "Are you currently residing within the EU?"
(Yes/No). The foreign-jurisdiction rule only covered work authorization, so the
question came back UNKNOWN, the required field stayed blank and the application
was staged for review (2026-10-30 night loop). The candidate lives in the US.
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

US_PROFILE = {"city": "Auburn", "state": "Washington", "country": "United States", "citizenshipCountry": "India"}


def test_us_resident_is_not_residing_in_the_eu():
    res = resolve_answer("Are you currently residing within the EU?", US_PROFILE, options=["Yes", "No"])
    assert res.answer == "No"


def test_us_resident_is_not_living_in_canada():
    res = resolve_answer("Do you currently live in Canada?", US_PROFILE, options=["Yes", "No"])
    assert res.answer == "No"


def test_residence_question_naming_the_us_is_left_alone():
    res = resolve_answer("Are you currently residing in the US or Canada?", US_PROFILE, options=["Yes", "No"])
    assert res.answer != "No"
