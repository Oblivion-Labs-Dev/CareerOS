"""Session fingerprints must vary, stay internally consistent, and retire when blocked.

The previous stealth profile injected one fixed identity into every session —
the same WebGL strings, plugins and languages every time — which is itself a
signature a detection vendor can match on. These tests pin the three properties
that make rotation worth having.
"""

from __future__ import annotations

import random

from app.services.application_assistant.browser_fingerprint import (
    FingerprintPool,
    build_evasion_script,
    generate_fingerprint,
)


def test_profiles_are_internally_coherent():
    """An incoherent identity is worse than none.

    A macOS user-agent reporting Win32 with an ANGLE/Direct3D renderer is a
    stronger tell than no spoofing, so OS family, platform string and GPU must
    always agree.
    """
    for _ in range(300):
        fp = generate_fingerprint()
        is_mac_ua = "Macintosh" in fp.user_agent
        assert is_mac_ua == (fp.platform == "MacIntel")
        if fp.platform == "MacIntel":
            assert "ANGLE" not in fp.webgl_renderer
            assert "Direct3D" not in fp.webgl_renderer
        else:
            assert "Apple" not in fp.webgl_renderer


def test_identities_actually_vary():
    """The whole point: not one identity reused for every session."""
    keys = {generate_fingerprint().key for _ in range(200)}
    assert len(keys) > 5


def test_generation_is_reproducible_for_a_seeded_rng():
    a = generate_fingerprint(random.Random(1234))
    b = generate_fingerprint(random.Random(1234))
    assert a == b


def test_blocked_fingerprint_is_not_reissued_for_that_host():
    pool = FingerprintPool()
    burned = pool.acquire("jobs.ashbyhq.com")
    pool.report_blocked("jobs.ashbyhq.com", burned)
    reissued = {pool.acquire("jobs.ashbyhq.com").key for _ in range(50)}
    assert burned.key not in reissued


def test_a_block_on_one_host_does_not_burn_the_identity_everywhere():
    """Being challenged by Ashby says nothing about Greenhouse.

    Seeded rather than sampled: an unseeded draw only has a *chance* of
    reproducing the burned fingerprint, so a fixed number of draws was really
    testing "is the fingerprint space small enough to hit by luck" — flaky
    for any pool size where that chance isn't near 1. Reusing the same seed
    forces the identical candidate and proves directly that it was never
    filtered out for a host it wasn't blocked on.
    """
    pool = FingerprintPool()
    burned = pool.acquire("jobs.ashbyhq.com", rng=random.Random(42))
    pool.report_blocked("jobs.ashbyhq.com", burned)
    reacquired = pool.acquire("boards.greenhouse.io", rng=random.Random(42))
    assert reacquired.key == burned.key


def test_ban_list_clears_rather_than_running_out():
    """A stale ban list is worse than a fresh guess, so exhaustion resets it."""
    pool = FingerprintPool(max_attempts=3)
    for _ in range(200):
        pool.report_blocked("jobs.ashbyhq.com", pool.acquire("jobs.ashbyhq.com"))
    assert pool.acquire("jobs.ashbyhq.com") is not None


def test_generated_values_reach_the_injected_script():
    fp = generate_fingerprint(random.Random(7))
    script = build_evasion_script(fp)
    assert fp.webgl_vendor in script
    assert fp.webgl_renderer in script
    assert fp.platform in script
    assert str(fp.hardware_concurrency) in script
    # The automation tell must still be covered by the parameterised version.
    assert "navigator, 'webdriver'" in script


def test_pool_snapshot_reports_retirements():
    pool = FingerprintPool()
    fp = pool.acquire("www.okta.com")
    pool.report_blocked("www.okta.com", fp)
    snap = pool.snapshot()
    assert snap["www.okta.com"]["blockEvents"] == 1
    assert snap["www.okta.com"]["retiredFingerprints"] == 1
