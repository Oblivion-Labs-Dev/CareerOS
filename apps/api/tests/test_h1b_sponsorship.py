from app.services.job_discover.h1b_sponsorship import apply_h1b_fields, check_h1b_sponsorship


def test_detects_likely_sponsorship():
    result = check_h1b_sponsorship("We offer visa sponsorship and welcome H-1B candidates.")
    assert result["status"] == "likely"
    assert result["signals"]


def test_detects_unlikely_sponsorship():
    result = check_h1b_sponsorship(
        "Must be authorized to work in the US without sponsorship. No visa sponsorship available."
    )
    assert result["status"] == "unlikely"


def test_apply_h1b_fields_on_job():
    job = apply_h1b_fields(
        {
            "title": "Software Engineer",
            "description": "No visa sponsorship. US work authorization required.",
        }
    )
    assert job["h1bStatus"] == "unlikely"
    assert job["h1bLabel"] == "Unlikely H1B"
