"""The autofill must use only the running user's own profile.

It used to fall back to the original author's name, city and resume path when
a profile field was empty, which would put someone else's identity on a real
application for any other user.
"""

from pathlib import Path

from app.services.application_assistant import playwright_autopilot_executor as ex


def test_empty_profile_gives_no_location_to_type():
    assert ex.application_location_query({}) == ("", "")
    assert ex.application_location_query({"location": "None"}) == ("", "")


def test_location_comes_from_the_profile():
    assert ex.application_location_query({"location": "Austin, TX"}) == ("Austin, TX", "Austin")
    assert ex.application_location_query({"location": "Austin, TX", "city": "Round Rock"}) == (
        "Austin, TX",
        "Round Rock",
    )
    assert ex.application_location_query({"city": "Denver"}) == ("Denver", "Denver")


def test_resume_name_is_built_from_the_profile(tmp_path, monkeypatch):
    monkeypatch.delenv("CAREEROS_RESUME_PATH", raising=False)
    f = tmp_path / "apjob_123_aggressive.pdf"
    assert ex.resume_display_name({"firstName": "Sam", "lastName": "O'Neil"}, f) == "Sam_ONeil_Resume.pdf"
    assert ex.resume_display_name({}, f) == "apjob_123_aggressive.pdf"


def test_resume_name_falls_back_to_the_configured_file(tmp_path, monkeypatch):
    mine = tmp_path / "My Resume.pdf"
    monkeypatch.setenv("CAREEROS_RESUME_PATH", str(mine))
    assert ex.resume_display_name({}, tmp_path / "x.pdf") == "My Resume.pdf"


def test_resume_path_comes_from_profile_or_env_only(tmp_path, monkeypatch):
    monkeypatch.setattr(ex, "FALLBACK_RESUME_PATH", tmp_path / "missing.pdf")
    monkeypatch.delenv("CAREEROS_RESUME_PATH", raising=False)
    assert ex.get_active_resume_path({}) == ""

    mine = tmp_path / "mine.pdf"
    mine.write_bytes(b"%PDF-1.4")
    monkeypatch.setenv("CAREEROS_RESUME_PATH", str(mine))
    assert ex.get_active_resume_path({}) == str(mine.resolve())

    other = tmp_path / "profile.pdf"
    other.write_bytes(b"%PDF-1.4")
    assert ex.get_active_resume_path({"resumePath": str(other)}) == str(other.resolve())


def test_no_personal_identity_in_the_executor_source():
    src = Path(ex.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    for token in ('"Akshay"', '"Borse"', "Akshay_Borse", r"D:\3 - Resources"):
        assert token not in code, token
