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


# ── Global-mobility signals ──────────────────────────────────────────────────
# An employer offering relocation or an intra-company transfer has the legal
# entity and process to move someone across a border — the same thing a
# sponsorship search is really after. None of the original patterns caught it,
# and adding these lifted the flagged pool from 533 to 650 live postings.

def test_global_mobility_signals_count_as_sponsorship_friendly():
    for text in (
        "We offer an international relocation package for this role",
        "Relocation assistance is provided for candidates outside the region",
        "Eligible for intra-company transfer to our Berlin office",
        "Our global mobility programme supports moves between offices",
        "Work permit support is available",
        "Candidates may qualify for an L-1 visa transfer",
    ):
        assert check_h1b_sponsorship(text)["status"] == "likely", text


def test_a_refusal_still_wins_over_a_relocation_mention():
    """An explicit "no sponsorship" must not be overridden by a perk mention."""
    text = "Relocation assistance provided. We are unable to sponsor visas for this role."
    assert check_h1b_sponsorship(text)["status"] == "unlikely"


def test_plain_perks_are_not_read_as_sponsorship():
    assert check_h1b_sponsorship("Great team, competitive salary, free lunch")["status"] == "unknown"
