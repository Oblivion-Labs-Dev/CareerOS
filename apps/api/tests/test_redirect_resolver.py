"""Tracking hops must resolve to the employer's real application URL.

Every shape here was taken from a live Indeed pull. The hops matter for two
reasons: the ATS handling cannot recognise an opaque tracking link, and dedup
keys off the ATS id in the URL, so the same posting arrives repeatedly under
different tracking ids when the hop is stored as-is.
"""

from __future__ import annotations

import pytest

from app.services.job_discover.redirect_resolver import (
    _extract_body_redirect,
    _unwrap_nested_url,
    is_redirector,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://click.appcast.io/t/abc123", True),
        ("https://grnh.se/eb0e4e3f4us", True),
        ("https://tnl2.jometer.com/v2/job?jz=5wqzs", True),
        ("https://jsv3.recruitics.com/redirect?rx=abc", True),
        # Real destinations must never be treated as hops.
        ("https://job-boards.greenhouse.io/torcrobotics/jobs/8703221002", False),
        ("https://jobs.uber.com/en/jobs/302443/", False),
        ("", False),
    ],
)
def test_redirector_detection(url, expected):
    assert is_redirector(url) is expected


def test_appcast_navigate_to_destination_is_extracted():
    """Appcast answers 200 and hides the destination in a navigateTo() call.

    The assignment inside the page is to a *variable* (`browser.location.href =
    url`), so matching on `location.href = "..."` alone never sees it — the
    literal only appears as navigateTo's last argument.
    """
    body = (
        '<html><head><title>Redirecting...</title><script type="text/javascript">'
        "function navigateTo(browser, window, url) { if (browser != window) { "
        'browser.location.href = url; window.location.replace("about:blank"); } '
        "else { window.location.replace(url); } } var timeout = 0; "
        'setTimeout(function(){ navigateTo(window.parent, window, '
        '"https://careers.humana.com/us/en/job/HUM429469/Senior-DevOps-Platform-Engineer'
        '?utm_source=appcast_indeed"); }, timeout);</script></head></html>'
    )
    out = _extract_body_redirect(body, "https://click.appcast.io/t/abc")
    assert out.startswith("https://careers.humana.com/us/en/job/HUM429469/")


def test_about_blank_decoy_is_not_treated_as_the_destination():
    """The same script calls location.replace("about:blank") as a decoy."""
    body = '<script>window.location.replace("about:blank");</script>'
    assert _extract_body_redirect(body, "https://click.appcast.io/t/abc") == ""


def test_meta_refresh_destination_is_extracted():
    body = '<meta http-equiv="refresh" content="0;url=https://boards.greenhouse.io/acme/jobs/123">'
    assert _extract_body_redirect(body, "https://grnh.se/x") == (
        "https://boards.greenhouse.io/acme/jobs/123"
    )


def test_ats_host_is_found_even_without_a_redirect_statement():
    body = '<a href="https://walmart.wd504.myworkdayjobs.com/WalmartExternal/job/USA-TX">Apply</a>'
    assert "myworkdayjobs.com" in _extract_body_redirect(body, "https://click.appcast.io/t/x")


def test_nested_destination_is_unwrapped_from_the_query_string():
    """Appcast lands on a wrapper whose `r` param holds the real posting."""
    wrapped = "https://careers.walmart.com?r=https://walmart.wd504.myworkdayjobs.com/WalmartExternal/job/123"
    assert _unwrap_nested_url(wrapped) == (
        "https://walmart.wd504.myworkdayjobs.com/WalmartExternal/job/123"
    )


def test_plain_url_is_left_alone_by_unwrapping():
    plain = "https://jobs.uber.com/en/jobs/302443/"
    assert _unwrap_nested_url(plain) == plain
