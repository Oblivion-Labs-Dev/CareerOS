"""Read a résumé's structure, not four regexes over the whole document.

`parse_resume_fields` extracted an email, a phone number, a years figure, and
the first line as the candidate's name. Nothing else — which is why a profile
built by uploading a résumé still had no employers, no degrees and no dates, and
why all of that was later typed in by hand.

Two properties matter more than coverage here, and most of these pin them down:
nothing is ever invented, and nothing already on the profile is overwritten.
"""

from __future__ import annotations

import pytest

from app.services.resume_parser import parse_resume_fields
from app.services.resume_structure import (
    parse_education,
    parse_experience,
    parse_skills,
    parse_structure,
    split_sections,
)

RESUME = """Akshay Borse
Seattle, WA | amsborse@gmail.com | (206) 555-0134

EXPERIENCE

Microsoft
Senior Software Engineer    Sept 2025 - Present
- Built an ingestion pipeline

Amazon    Software Engineer II    08/2019 - 08/2025
- Order management platform

Persistent Systems | Software Engineer | September 2016 - July 2017
- Early career work

EDUCATION

Santa Clara University, Master of Science in Computer Science    2017 - 06/2019
Pune University - Bachelor of Engineering in Computer Science    09/2012 - 06/2016

SKILLS
Languages: Python, Java, Go, TypeScript
Cloud: AWS, Kubernetes
"""


# ── Sections ─────────────────────────────────────────────────────────────────


def test_sections_are_found_by_heading():
    sections = split_sections(RESUME)

    assert set(sections) >= {"header", "experience", "education", "skills"}
    assert "Akshay Borse" in sections["header"][0]


def test_a_heading_word_inside_a_sentence_does_not_open_a_section():
    """"my education prepared me…" in a summary is prose, not a heading."""
    sections = split_sections("SUMMARY\nMy education prepared me for this.\nEXPERIENCE\nAcme  2020 - 2021\n")

    assert "My education prepared me for this." in sections["summary"]
    assert not sections.get("education")


# ── Employment ───────────────────────────────────────────────────────────────


def test_every_employer_is_read_with_its_dates():
    experience = parse_experience(split_sections(RESUME)["experience"])

    assert [entry["company"] for entry in experience] == ["Microsoft", "Amazon", "Persistent Systems"]
    assert experience[1]["title"] == "Software Engineer II"
    assert experience[1]["startDate"] == "08/2019"
    assert experience[1]["endDate"] == "08/2025"


def test_a_current_role_is_marked_rather_than_given_an_end_date():
    experience = parse_experience(split_sections(RESUME)["experience"])

    assert experience[0]["currentlyEmployed"] is True
    assert experience[0]["endDate"] == ""


def test_bullet_points_never_become_employers():
    """The regression this file exists for.

    The line above a dated line was folded in to find the company name, which
    made the previous role's bullet ("- Built an ingestion pipeline") the next
    employer.
    """
    experience = parse_experience(split_sections(RESUME)["experience"])

    assert all(not entry["company"].startswith("-") for entry in experience)


@pytest.mark.parametrize(
    "line",
    [
        "Acme Corp    Engineer    Jan 2020 - Mar 2022",
        "Acme Corp | Engineer | 01/2020 – 03/2022",
        "Acme Corp    Engineer    2020 to 2022",
    ],
)
def test_the_separators_resumes_actually_use_are_handled(line):
    """Hyphen, en dash and the word "to" all appear in the wild; a parser that
    handles only one silently drops the rest."""
    entries = parse_experience([line])

    assert entries and entries[0]["company"] == "Acme Corp"


# ── Education ────────────────────────────────────────────────────────────────


def test_both_degrees_are_read():
    education = parse_education(split_sections(RESUME)["education"])

    assert len(education) == 2
    assert education[0]["school"] == "Santa Clara University"
    assert education[1]["school"] == "Pune University"


def test_the_school_is_not_the_whole_line():
    education = parse_education(split_sections(RESUME)["education"])

    assert education[1]["school"] == "Pune University"
    assert "Bachelor" not in education[1]["school"]


def test_the_degree_is_canonicalised():
    education = parse_education(split_sections(RESUME)["education"])

    assert education[0]["degree"] == "Master's Degree"
    assert education[1]["degree"] == "Bachelor's Degree"


def test_the_field_of_study_is_not_the_degrees_own_name():
    """"Master of Science in Computer Science" must not yield "Science in
    Computer Science" — the degree name swallowing the field."""
    education = parse_education(split_sections(RESUME)["education"])

    assert education[0]["discipline"] == "Computer Science"


def test_a_field_of_study_is_never_borrowed_from_the_next_entry():
    """A fixed multi-line window read the following school's subject onto this
    one — a factual error on an application, not a cosmetic one."""
    text = "EDUCATION\nAlpha University | BSc in Physics | 2010 - 2014\nBeta College | MSc in Chemistry | 2015 - 2017\n"

    education = parse_education(split_sections(text)["education"])

    assert education[0]["discipline"] == "Physics"
    assert education[1]["discipline"] == "Chemistry"


def test_an_entry_spread_over_several_lines_is_read():
    text = "EDUCATION\nStanford University\nBachelor of Arts in Economics\n2014 - 2018\n"

    education = parse_education(split_sections(text)["education"])

    assert education[0]["discipline"] == "Economics"
    assert education[0]["startDate"] == "2014"


def test_an_absent_field_is_omitted_rather_than_guessed():
    text = "EDUCATION\nOxford University | MSc Physics | 2020 - 2022\n"

    entry = parse_education(split_sections(text)["education"])[0]

    assert "discipline" not in entry, "no in/of clause means no field of study to read"
    assert entry["degree"] == "Master's Degree"


# ── Skills ───────────────────────────────────────────────────────────────────


def test_skills_drop_their_category_prefix():
    skills = parse_skills(split_sections(RESUME)["skills"])

    assert "Python" in skills
    assert "AWS" in skills
    assert not any(skill.startswith("Languages") for skill in skills)


# ── Merging into the profile ─────────────────────────────────────────────────


def test_structure_reaches_an_empty_profile():
    updated, extracted = parse_resume_fields(RESUME, {})

    assert len(updated["workExperience"]) == 3
    assert len(updated["education"]) == 2
    assert extracted["education"]


def test_an_existing_profile_is_never_silently_overwritten():
    """A résumé is evidence; the profile is the record the candidate approved.
    Re-parsing an old PDF must not wipe their corrections.
    """
    existing = {"education": [{"school": "Corrected By Hand"}]}

    updated, extracted = parse_resume_fields(RESUME, existing)

    assert updated["education"] == existing["education"], "profile wins"
    assert len(extracted["education"]) == 2, "but the parse is still reported for review"


def test_a_resume_with_no_recognisable_sections_yields_nothing():
    assert parse_structure("Just a paragraph about me with no headings at all.") == {}
