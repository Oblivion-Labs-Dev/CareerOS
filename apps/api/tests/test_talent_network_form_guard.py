"""A Radancy talent-network signup is not an application form.

NetApp's, Sony Pictures', Jack Henry's and Unifirst's posting pages carry a
job-alert signup (name, email, keyword + location, posted to /form/submit),
which the runner filled as if it were the application.
"""

from __future__ import annotations

import asyncio

from app.services.application_assistant.domain import IneligibilityReason
from app.services.application_assistant.ineligibility import _first_text_match
from app.services.application_assistant.playwright_autopilot_executor import (
    _TALEO_ENTERPRISE,
    _has_visible_password_field,
    _only_talent_network_forms,
)

SEL = '#first_name, #email, input[id*="first_name" i], input[name*="first_name" i], input[name*="last_name" i]'

RADANCY = """
<form action="https://careers.example.com/form/submit" data-form>
  <input id="form-field-1-first_name" name="first_name"><input name="last_name">
  <input class="keyword-location" data-keyword-list="kw" name="Location">
</form>
"""

GREENHOUSE = """
<form id="application-form" action="/apply">
  <input id="first_name"><input id="email">
  <label><input type="checkbox"> Join our talent community</label>
</form>
"""


from tests.browser_test_utils import eval_in_pooled_page


def _talent_only(html: str) -> bool:
    return eval_in_pooled_page(
        f"<html><body>{html}</body></html>",
        lambda page: _only_talent_network_forms(page, SEL),
    )


def test_radancy_job_alert_signup_is_not_an_application():
    assert _talent_only(RADANCY)


def test_a_real_application_form_is_kept():
    assert not _talent_only(GREENHOUSE)


def test_an_application_beside_a_signup_is_kept():
    assert not _talent_only(RADANCY + GREENHOUSE)


PERATON = """
<div class="contact-modal2_component">
  <h2>INTEREST FORM</h2>
  <p>Use this form to quickly share your info and resume—no lengthy application required.</p>
  <div class="contact-modal2_form-block">
    <form id="application-form" class="contact-modal2_form">
      <label>First Name</label><input id="first_name" name="first_name">
      <label>Email</label><input id="email" name="email">
    </form>
  </div>
</div>
"""

INTEREST_IN_FORM = """
<form id="lead">
  <h3>Expression of interest</h3>
  <input id="first_name">
</form>
"""

APPLICATION_MENTIONING_INTEREST = """
<form id="application-form" action="/apply">
  <h2>Apply for this job</h2>
  <input id="first_name"><input id="email">
  <label>Why are you interested in this role? (no lengthy application required)</label>
  <textarea></textarea>
</form>
"""


def test_peraton_interest_form_is_not_an_application():
    assert _talent_only(PERATON)


def test_interest_heading_inside_the_form_is_recognised():
    assert _talent_only(INTEREST_IN_FORM)


def test_interest_wording_after_the_first_field_is_ignored():
    assert not _talent_only(APPLICATION_MENTIONING_INTEREST)


TALEO_ACCOUNT = """
<form><label>Email</label><input id="email">
  <label>Password</label><input type="password" name="pw">
  <label>Re-type new password:</label><input type="password" name="pw2">
  <label>First Name</label><input id="first_name"></form>
"""

HIDDEN_PASSWORD = """
<form><input id="first_name"><input type="password" style="display:none"></form>
"""


def _has_password(html: str) -> bool:
    return eval_in_pooled_page(
        f"<html><body>{html}</body></html>",
        lambda page: _has_visible_password_field(page),
    )


def test_account_creation_form_is_detected():
    assert _has_password(TALEO_ACCOUNT)


def test_hidden_password_input_is_ignored():
    assert not _has_password(HIDDEN_PASSWORD)
    assert not _has_password(GREENHOUSE)


def test_taleo_enterprise_is_account_gated_but_business_edition_is_checked_by_form():
    assert _TALEO_ENTERPRISE.search("https://uhg.taleo.net/careersection/10000/jobdetail.ftl?job=2390003")
    assert _TALEO_ENTERPRISE.search("https://uhg.taleo.net/careersection/application.jss?lang=en&type=1")
    assert not _TALEO_ENTERPRISE.search(
        "https://phh.tbe.taleo.net/phh01/ats/careers/v2/viewRequisition?org=BASESOLU&cws=37&rid=5245"
    )


def test_account_reason_routes_to_manual_application():
    reason = _first_text_match(
        "This employer's apply flow requires a candidate account (the form asks for a "
        "password), which Autopilot does not create - apply by hand."
    )
    assert reason == IneligibilityReason.MANUAL_APPLICATION_REQUIRED
