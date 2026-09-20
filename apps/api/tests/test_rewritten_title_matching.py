"""Aggregators rewrite job titles; matching has to survive that without guessing.

jaabz republishes one Parallel role as "Senior Security Engineer (Application &
AI Agent Security)" while the employer's own Ashby board calls it "Member of
Technical Staff, Product Security" — the two share only the word "security", so
the 60%-overlap test rejects a correct match.

The fallback accepts a rewritten title only when exactly one posting on the
board is plausibly the same role. That restraint matters more than the extra
coverage: picking between two similar postings means applying to the wrong job.
Measured effect of the fallback: jaabz 4/20 -> 5/20, LinkedIn 8/25 -> 9/25.
"""

from __future__ import annotations

from app.services.job_discover.aggregator_resolve import _distinctive_tokens, _match_job


def _board(*titles: str) -> list[dict[str, str]]:
    return [{"title": t, "absolute_url": f"https://example.com/{i}"} for i, t in enumerate(titles)]


def test_rewritten_title_matches_when_one_role_is_plausible():
    jobs = _board(
        "GTM, Enterprise",
        "Product Designer",
        "Member of Technical Staff, Product Security",
        "Deployed Engineer",
    )
    match = _match_job(jobs, "Senior Security Engineer (Application & AI Agent Security)")
    assert match is not None
    assert match["title"] == "Member of Technical Staff, Product Security"


def test_two_plausible_roles_are_refused_rather_than_guessed():
    """The real Parallel board case.

    It genuinely lists both Product Security and Infrastructure Security, and
    the rewritten title says "Application", which matches neither. Returning
    either one would be a coin flip against applying to the wrong role.
    """
    jobs = _board(
        "Member of Technical Staff, Product Security",
        "Member of Technical Staff, Infrastructure Security",
    )
    assert _match_job(jobs, "Senior Security Engineer (Application & AI Agent Security)") is None


def test_sharing_only_boilerplate_words_is_not_a_match():
    """"Senior", "engineer" and "software" are on nearly every posting."""
    jobs = _board("Senior Data Scientist", "Principal Product Manager")
    assert _match_job(jobs, "Senior Software Engineer") is None


def test_generic_words_are_excluded_from_the_distinctive_set():
    assert _distinctive_tokens("Senior Staff Software Engineer II") == set()
    assert "security" in _distinctive_tokens("Senior Security Engineer")
    assert "payments" in _distinctive_tokens("Staff Engineer, Payments")


def test_strict_overlap_still_wins_when_it_applies():
    """The fallback must not displace a confident direct match."""
    jobs = _board("Senior Software Engineer, Payments", "Security Engineer")
    match = _match_job(jobs, "Senior Software Engineer, Payments")
    assert match is not None
    assert match["title"] == "Senior Software Engineer, Payments"


def test_empty_board_is_handled():
    assert _match_job([], "Senior Security Engineer") is None
