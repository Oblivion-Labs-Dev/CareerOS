"""Regressions found by replaying real applications in dry-run mode (2026-10-30).

Each test renders the shape of the live page that failed (Ashby, Lever,
Workable, Phenom, SuccessFactors) in a real Chromium page and runs the
production reader, locator or fill pass against it. None of them submits.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.application_assistant.browser_runner import run_playwright
from app.services.application_assistant.browser_verifier import verify_browser_dom_state
from app.services.application_assistant.playwright_autopilot_executor import (
    APPLICATION_FORM_SELECTOR,
    EXPIRED_TEXT_PATTERNS,
    _extract_dom_form_state,
    _fill_native_selects,
    _locate_field,
    _phenom_already_applied,
    _phenom_step_button,
    _select_radio_option,
)
from app.services.application_assistant.form_reviewer import review_and_heal_form_state
from tests.browser_test_utils import eval_in_pooled_page

# Lever: question text in a sibling .application-label, controls carry only a
# name. The EEO block instead wraps a plain <div> question in a <label>.
LEVER_HTML = """
<form>
  <ul><li class="application-question">
    <div class="application-label"><div class="text">LinkedIn URL<span class="required">✱</span></div></div>
    <div class="application-field"><input type="text" name="urls[LinkedIn]" required></div>
  </li></ul>
  <div class="application-question">
    <div class="application-label full-width dropdown"><div class="text">Are you legally authorized to work in the location where this role is based?<span class="required">✱</span></div></div>
    <div class="application-field full-width required-field"><div class="application-dropdown">
      <select name="cards[3655][field0]" required>
        <option value="">Select...</option>
        <option value="Yes, I am authorized to work without sponsorship">Yes, I am authorized to work without sponsorship</option>
        <option value="Yes, but I will require visa sponsorship in the future">Yes, but I will require visa sponsorship in the future</option>
        <option value="No, I will require immediate visa sponsorship">No, I will require immediate visa sponsorship</option>
      </select></div></div>
  </div>
  <div class="application-question"><label>
    <div>Race</div>
    <div class="application-field"><div class="application-dropdown"><select name="eeo[race]">
      <option value="">Select ...</option>
      <option value="White (Not Hispanic or Latino)">White (Not Hispanic or Latino)</option>
      <option value="Asian (Not Hispanic or Latino)">Asian (Not Hispanic or Latino)</option>
      <option value="Decline to self-identify">Decline to self-identify</option>
    </select></div></div>
  </label></div>
  <div class="application-question">
    <div class="application-label"><div class="text">Are you willing to relocate?<span class="required">✱</span></div></div>
    <div class="application-field"><ul>
      <li><label><input type="radio" name="cards[3655][field1]" value="Yes"> Yes</label></li>
      <li><label><input type="radio" name="cards[3655][field1]" value="No"> No</label></li>
    </ul></div>
  </div>
</form>
"""

# Workable: the input sits inside its <label>, the question in a nested span
# after a "*" marker; the control has a name and no id.
WORKABLE_HTML = """
<form><div>
  <label><span><strong>*</strong></span><span>What is your expected compensation for this role?</span>
    <input type="text" name="QA_12649654" required></label>
</div></form>
"""

PROFILE = {"firstName": "Akshay", "lastName": "Borse", "email": "a@example.com", "raceEthnicity": "Asian"}


def _labels(fields):
    return {f.get("name"): f.get("label") for f in fields}


def test_lever_and_workable_questions_are_read_by_their_text_not_their_name():
    async def read(page):
        fields, _ = await _extract_dom_form_state(page)
        return _labels(fields)

    lever = eval_in_pooled_page(LEVER_HTML, read)
    assert lever["urls[LinkedIn]"] == "LinkedIn URL"
    assert lever["cards[3655][field0]"].startswith("Are you legally authorized")
    assert lever["eeo[race]"] == "Race"
    assert eval_in_pooled_page(WORKABLE_HTML, read)["QA_12649654"] == (
        "What is your expected compensation for this role?"
    )


def test_the_verifier_names_an_empty_lever_question_by_its_text():
    async def missing(page):
        result = await verify_browser_dom_state(page, [], PROFILE)
        return [i.label for i in result.issues if i.issue_type == "MISSING_REQUIRED"]

    labels = " | ".join(eval_in_pooled_page(LEVER_HTML, missing))
    assert "LinkedIn URL" in labels
    assert "urls[LinkedIn]" not in labels


def test_a_select_on_its_placeholder_is_read_as_unanswered():
    async def value(page):
        fields, _ = await _extract_dom_form_state(page)
        return {f["name"]: f["value"] for f in fields}["cards[3655][field0]"]

    assert eval_in_pooled_page(LEVER_HTML, value) == ""


def test_the_reviewer_points_healing_at_a_name_only_field():
    review = asyncio.run(review_and_heal_form_state(
        form_state=[{"id": "", "name": "QA_12649654", "label": "Expected compensation", "required": True,
                     "value": "", "type": "text"}],
        validation_errors=[], profile=PROFILE, company="Acme", title="Engineer",
    ))
    assert [m["fieldId"] for m in review["missingOrInvalidFields"]] == ["QA_12649654"]


def test_name_only_fields_can_be_located_and_filled():
    async def run(page):
        field = await _locate_field(page, "QA_12649654")
        await field.fill("$140,000")
        return await page.input_value('[name="QA_12649654"]')

    assert eval_in_pooled_page(WORKABLE_HTML, run) == "$140,000"

    async def radio(page):
        ok = await _select_radio_option(page, "cards[3655][field1]", "Yes")
        return ok, await page.is_checked('input[name="cards[3655][field1]"][value="Yes"]')

    assert eval_in_pooled_page(LEVER_HTML, radio) == (True, True)


def test_native_selects_never_volunteer_an_optional_lever_race_question():
    async def run(page):
        filled: dict[str, str] = {}
        await _fill_native_selects(await page.locator('select[name="eeo[race]"]').all(), page, PROFILE, [], filled, {})
        return await page.input_value('select[name="eeo[race]"]'), filled

    race, filled = eval_in_pooled_page(LEVER_HTML, run)
    assert race == "", f"optional race was volunteered: {filled}"
    assert "Select ..." not in filled


def test_a_required_race_dropdown_is_still_answered():
    html = LEVER_HTML.replace('<select name="eeo[race]">', '<select name="eeo[race]" required>')

    async def run(page):
        await _fill_native_selects(await page.locator('select[name="eeo[race]"]').all(), page, PROFILE, [], {}, {})
        return await page.input_value('select[name="eeo[race]"]')

    assert eval_in_pooled_page(html, run) == "Asian (Not Hispanic or Latino)"


@pytest.mark.parametrize("html", [
    '<form><input name="_systemfield_name"><input name="_systemfield_email" type="email"></form>',  # Ashby
    '<form><input type="text" name="name"><input type="email" name="email"></form>',  # Lever
])
def test_ashby_and_lever_forms_are_recognised_as_application_forms(html):
    assert eval_in_pooled_page(html, lambda page: page.locator(APPLICATION_FORM_SELECTOR).count()) > 0


def test_ashby_missing_job_wording_reads_as_expired():
    text = "Job not found - The job you requested was not found.".lower()
    assert any(pattern in text for pattern in EXPIRED_TEXT_PATTERNS)


def test_phenom_already_applied_page_is_recognised():
    assert _phenom_already_applied(
        "https://careers.fiserv.com/us/en/applythankyou?status=alreadyApplied&jobSeqNo=X"
    )
    assert not _phenom_already_applied("https://careers.fiserv.com/us/en/applythankyou?status=success")
    assert not _phenom_already_applied("https://careers.fiserv.com/us/en/apply?step=1")


def test_phenom_step_button_waits_for_a_step_still_rendering():
    html = """<div id="root"></div><script>
      setTimeout(() => { document.getElementById('root').innerHTML = '<button id="next">Next</button>'; }, 1200);
    </script>"""

    async def run(page):
        found = await _phenom_step_button(page)
        return found[0] if found else None

    assert eval_in_pooled_page(html, run) == "next"


def test_a_whole_name_field_is_not_compared_with_the_surname():
    html = """<form><div class="field"><label for="n">Legal First and Last Name *</label>
      <input id="n" name="_systemfield_name" value="Akshay Borse" required></div></form>"""

    async def run(page):
        result = await verify_browser_dom_state(page, [], PROFILE)
        return [(i.issue_type, i.label) for i in result.issues if i.severity == "BLOCKING"]

    assert eval_in_pooled_page(html, run) == []


SIGN_IN_HTML = b"""<!doctype html><html><body><h2>Career Opportunities: Sign In</h2>
<form action="/signin" method="post">
  <label for="email">Email Address:*</label><input id="email" type="email" name="email" required>
  <label for="pw">Password:*</label><input id="pw" type="password" name="password" required>
  <button type="submit">Sign In</button>
</form></body></html>"""


def test_a_sign_in_page_that_rendered_late_is_never_submitted(monkeypatch, tmp_path):
    """SuccessFactors (Purpose Financial): the account check ran before the
    sign-in page had rendered, the email box then counted as a filled form,
    and the run went looking for a submit button on a login page."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.services.application_assistant import playwright_autopilot_executor as executor

    monkeypatch.setattr(executor, "SCREENSHOTS_DIR", tmp_path)
    posts: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(SIGN_IN_HTML)

        def do_POST(self):
            posts.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    real_check = executor._has_visible_password_field
    calls = {"n": 0}

    async def first_check_misses(frame):
        # The first look happens before the page has drawn its password box.
        calls["n"] += 1
        return False if calls["n"] == 1 else await real_check(frame)

    monkeypatch.setattr(executor, "_has_visible_password_field", first_check_misses)
    marker_calls: list[int] = []

    async def marker():
        marker_calls.append(1)

    try:
        # On the shared Playwright loop, like the other browser tests: the pooled
        # browser belongs to that loop, and driving it from a fresh asyncio.run()
        # loop hangs once an earlier test has started the pool.
        result = run_playwright(executor.execute_live_playwright_submission(
            job_item={"id": "apjob_signin", "company": "Purpose Financial", "title": "Engineer",
                      "applicationUrl": f"http://127.0.0.1:{server.server_address[1]}/careers"},
            profile={"firstName": "Akshay", "lastName": "Borse", "email": "a@example.com", "phone": "4255550100"},
            answer_lib=[], headless=True, timeout_sec=120, on_submit_attempt=marker,
        ), timeout=180)
    finally:
        server.shutdown()

    assert not result.get("submitted")
    assert "candidate account" in (result.get("error") or ""), result.get("error")
    assert marker_calls == [] and posts == []


@pytest.mark.parametrize("question", [
    # Revstar (Workable): answered "YES" as if it were an accuracy attestation.
    "Databricks Certifications: Databricks Certified Data Engineer Professional and/or "
    "Machine Learning Professional preferred.",
    "Are you AWS certified?",
])
def test_a_credential_question_is_not_an_accuracy_attestation(question):
    from app.services.application_assistant.question_classifier import QuestionType, classify_question

    assert classify_question(question, "", None) != QuestionType.ACCURACY_CONFIRMATION


@pytest.mark.parametrize("question", [
    "I certify that the information provided is true and complete.",
    "By submitting, I hereby certify the above",
])
def test_an_accuracy_attestation_is_still_recognised(question):
    from app.services.application_assistant.question_classifier import QuestionType, classify_question

    assert classify_question(question, "", None) == QuestionType.ACCURACY_CONFIRMATION
