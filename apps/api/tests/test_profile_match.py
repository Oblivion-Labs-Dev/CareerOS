import pytest

from app.services.application_assistant.profile_match import profile_match

# Scores are pinned to a sample backend/platform engineer resume read.
pytestmark = pytest.mark.usefixtures("engineer_match_profile")


BACKEND = """Requirements:
- 5+ years building distributed systems and microservices in Java or Python
- Experience with AWS, Kubernetes and REST/gRPC APIs
- Familiarity with LLMs, RAG and AI agents is a plus"""
FRONTEND = """Requirements:
- 5+ years with React, CSS and design systems
- Accessibility and Figma experience"""
ANDROID = """Requirements:
- 5+ years of Android development in Kotlin
- Jetpack Compose experience"""


def score(title, body):
    return profile_match({"title": title, "description": body})["matchScore"]


def test_fit_ordering_matches_how_a_reviewer_would_rank():
    backend = score("Senior Backend Engineer", BACKEND)
    frontend = score("Senior Frontend Engineer", FRONTEND)
    android = score("Senior Android Engineer", ANDROID)
    assert backend >= 70 > frontend > android
    assert android < 20


def test_manager_and_title_skill_gap_are_held_down():
    assert score("Engineering Manager, Backend", BACKEND) < 50
    assert score("Senior Salesforce Engineer", BACKEND) < score("Senior Software Engineer", BACKEND)


def test_clearance_requirement_is_penalised():
    cleared = BACKEND + "\n- Active TS/SCI security clearance required"
    assert score("Senior Backend Engineer", cleared) < score("Senior Backend Engineer", BACKEND) - 15


def test_title_only_job_gets_a_neutral_reasoned_score():
    m = profile_match({"title": "Senior Software Engineer", "description": ""})
    assert 40 < m["matchScore"] < 90 and "title only" in m["matchReason"]


def comps(title, body):
    return profile_match({"title": title, "description": body})["matchComponents"]


def test_one_line_html_posting_still_finds_the_must_section():
    html_body = ("<p><strong>Requirements:</strong></p><ul><li>5+ years building distributed systems "
                 "in Java or Python</li><li>Experience with AWS &amp; Kubernetes</li></ul>")
    plain = score("Senior Backend Engineer", BACKEND)
    assert abs(score("Senior Backend Engineer", html_body) - plain) < 20
    assert score("Senior Backend Engineer", html_body) >= 60


def test_required_foreign_language_is_capped():
    body = BACKEND + "\n- Fluent Ukrainian is required"
    assert score("Senior Backend Engineer", body) <= 15
    assert comps("Senior Backend Engineer", body)["blockers"]


def test_bonus_line_does_not_hide_later_must_haves():
    body = ("Requirements:\nTechnical Skills: Proficiency in Python (Django experience is a bonus).\n"
            "- 5+ years building distributed systems\n- Fluent Ukrainian is required")
    assert score("Senior Backend Engineer", body) <= 15


def test_clearance_in_title_is_capped_but_ability_to_obtain_is_only_penalised():
    capped = score("Software Engineer (Cleared)", BACKEND)
    obtain = score("Senior Backend Engineer", BACKEND + "\n- Ability to obtain a security clearance")
    assert capped <= 15
    assert 15 < obtain < score("Senior Backend Engineer", BACKEND)


def test_twelve_plus_years_capped_but_company_history_years_ignored():
    assert score("Senior Backend Engineer", BACKEND.replace("5+", "12+")) <= 15
    history = BACKEND + "\nOur firm has over 20 years of experience delivering software."
    assert score("Senior Backend Engineer", history) >= 60


def test_embedded_and_defense_roles_score_low():
    body = ("Requirements:\n- 5+ years of embedded C on RTOS and microcontrollers\n"
            "- Firmware for FPGA boards, SPI/I2C, oscilloscope debugging")
    assert score("Senior Firmware Engineer", body) < 30
    assert comps("Senior Firmware Engineer", body)["family"] == "embedded"


def test_generic_only_posting_is_not_near_ninety():
    body = "Requirements:\n- Experience with REST APIs, SQL, Docker and CI/CD\n- Microservices"
    assert score("Software Engineer", body) < 80


def test_unknown_must_have_tech_is_a_gap_and_years_of_it_hurt():
    body = BACKEND + "\n- 5+ years of experience with DAML smart contracts"
    c = comps("Senior Backend Engineer", body)
    assert any("daml" in g.lower() for g in c["gaps"])
    assert c["hardSkillGap"]
    assert score("Senior Backend Engineer", body) < score("Senior Backend Engineer", BACKEND) - 15


def test_student_and_intern_titles_score_low():
    assert score("Software Engineering Intern", BACKEND) < 30
    assert score("Student Software Developer (Part-Time)", BACKEND) < 30
