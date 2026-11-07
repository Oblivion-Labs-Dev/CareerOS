"""Uploading a resume gives job matching a profile of that person, with no model call."""

import base64
import json

import pytest

from app.services.application_assistant import match_profile_builder as builder
from app.services.application_assistant import profile_match
from app.services.resume_parser import parse_resume_into_profile

SWE_RESUME = """Jordan Lee
jordan.lee@example.com | (555) 010-2000
Senior Software Engineer, Example Corp, 2018 - present
- Built distributed systems in Python and Java serving 40k requests per second.
- Designed REST APIs and Kafka event-driven pipelines on AWS (Lambda, S3, DynamoDB).
- Ran services on Kubernetes with Terraform, CI/CD in GitHub Actions, and Prometheus monitoring.
- Wrote Python tooling and PostgreSQL schemas; mentored four engineers.
Skills: Python, Java, SQL, AWS, Kubernetes, Docker, Kafka
"""

PM_RESUME = """Sam Rivera
sam.rivera@example.com | (555) 010-3000
Senior Product Manager, Example Retail, 2017 - present
- Owned the product roadmap and product strategy for the checkout experience.
- Ran A/B tests and experimentation with Amplitude and Looker dashboards.
- Wrote PRDs, aligned stakeholders across engineering, design and marketing.
- Led go-to-market for a marketplace launch; worked in agile scrum teams with Jira.
- Partnered with user research on usability studies and Figma prototypes.
"""

NEUTRAL = {
    "resume_file": "",
    "family_fit": {"": 0.75},
    "seniority_fit": {str(i): 1.0 for i in range(6)},
    "skills": {}, "domains": {},
    "penalties": {"years_over": 99, "years_penalty": 0.0, "clearance_re": "top secret",
                  "clearance_penalty": 0.0, "cap": 15, "years_cap": 99, "language_re": ""},
}


@pytest.fixture
def neutral_bundled(tmp_path, monkeypatch):
    """The public build ships a neutral bundled profile; score as that build does."""
    path = tmp_path / "bundled.json"
    path.write_text(json.dumps(NEUTRAL), encoding="utf-8")
    monkeypatch.setattr(profile_match, "PROFILE_PATH", path)
    monkeypatch.delenv(profile_match.PROFILE_ENV, raising=False)
    profile_match.default_profile.cache_clear()
    return path


def _upload(text: str, name: str = "resume.txt") -> dict:
    return {"defaultResume": {"name": name, "type": "text/plain",
                              "base64": base64.b64encode(text.encode()).decode("ascii")}}


def test_engineer_resume_reads_skills_family_and_level() -> None:
    profile = builder.build_match_profile(SWE_RESUME, title="Senior Software Engineer", years=8)
    skills = profile["skills"]
    assert skills["python"]["have"] >= 0.85
    assert skills["aws"]["have"] >= 0.7
    # Missing from the resume: a soft gap, never a hard "cannot do this" blocker.
    assert profile_match.HARD_GAP_HAVE < skills["swift_ios"]["have"] < 0.4
    assert profile["role_family"] in {"backend", "platform", "infrastructure"}
    assert profile["seniority"] == 3
    assert profile["seniority_fit"]["3"] == 1.0
    assert profile["seniority_fit"]["0"] < 0.5
    assert profile["penalties"]["years_over"] == 12
    profile_match.load_profile  # the shape must load as a real profile
    path = builder.GENERATED_PROFILE_PATH
    path.write_text(json.dumps(profile), encoding="utf-8")
    assert profile_match.load_profile(path).skills["python"][1] >= 0.85


def test_level_comes_from_years_when_the_title_states_none() -> None:
    assert builder.build_match_profile(SWE_RESUME, title="Software Engineer", years=1)["seniority"] == 1
    unknown = builder.build_match_profile(SWE_RESUME, title="Software Engineer")
    assert unknown["seniority"] is None
    assert unknown["seniority_fit"] == builder.NEUTRAL_SENIORITY_FIT
    assert unknown["penalties"]["years_penalty"] == 0.0


def test_too_little_text_fails_loudly_instead_of_meaning_no_skills() -> None:
    with pytest.raises(ValueError, match="too short"):
        builder.build_match_profile("Jordan Lee\nPython")


def test_parsing_a_pm_resume_makes_matching_prefer_pm_roles(neutral_bundled) -> None:
    before_pm = profile_match.profile_components("Senior Product Manager", "")["score"]
    before_swe = profile_match.profile_components("Senior Backend Engineer", "")["score"]

    result = parse_resume_into_profile({"currentTitle": "Senior Product Manager", "yearsExperience": 9},
                                       _upload(PM_RESUME), force=True)

    assert result["matchProfile"]["ok"] is True
    written = json.loads(builder.GENERATED_PROFILE_PATH.read_text(encoding="utf-8"))
    assert written["role_family"] == "product"
    assert written["resume_file"] == "resume.txt"
    pm = profile_match.profile_components("Senior Product Manager", "")["score"]
    swe = profile_match.profile_components("Senior Backend Engineer", "")["score"]
    assert before_pm == before_swe  # neutral until a resume is parsed
    assert pm > swe


def test_a_hand_tuned_bundled_profile_wins_over_the_generated_one(neutral_bundled) -> None:
    neutral_bundled.write_text(json.dumps({**NEUTRAL, "resume_file": "mine.pdf"}), encoding="utf-8")
    builder.write_match_profile(PM_RESUME, title="Product Manager")
    assert profile_match.resolve_profile_path() == neutral_bundled


def test_a_failed_profile_build_is_reported_and_the_parse_still_succeeds(neutral_bundled) -> None:
    short = "Jordan Lee\njordan.lee@example.com\n(555) 010-2000\n"
    result = parse_resume_into_profile({}, _upload(short), force=True)
    assert result["profile"]["email"] == "jordan.lee@example.com"
    assert result["matchProfile"]["ok"] is False
    assert "too short" in result["matchProfile"]["error"]
    assert not builder.GENERATED_PROFILE_PATH.exists()


@pytest.mark.parametrize("title", ["SDE II", "SWE", "Senior SWE"])
def test_short_engineer_titles_count_as_generalist_engineers(title) -> None:
    family, fit = builder._family_fit(title, "")
    assert family in builder.GENERALIST_FAMILIES
    assert fit["backend"] == 1.0
    assert builder._family_fit("Answer desk lead", "")[0] == ""
