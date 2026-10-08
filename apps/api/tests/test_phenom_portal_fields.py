"""Phenom portals (eBay, Fiserv, Mastercard, Regions, Republic Services).

Their first page stalled every run: native selects whose option values are
codes ("USA-WA", "USA_1", "APPLICANT_SOURCE-3-12"), phone device-type and
country-code dropdowns read as the phone number itself, a resume parser that
types into the address fields, and consent boxes the sweep never ticked.
The DOM cases run the real JS in Chromium.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.application_assistant.browser_verifier import (
    _match_dom_field,
    verify_browser_dom_state,
)
from app.services.application_assistant.pending_question_groups import _wording_pattern
from app.services.application_assistant.playwright_autopilot_executor import (
    _RADIO_GROUP_LABEL_JS,
    _drop_email_alias,
    _is_choice_group_checkbox,
    _is_phenom_apply_url,
    _phenom_education_row_id,
    _PHENOM_EDUCATION_ID,
    _phenom_step_name,
    _prefill_disagrees,
    _tick_checkbox,
)
from app.services.application_assistant.profile_answer_resolver import resolve_answer
from app.services.application_assistant.question_classifier import QuestionType, classify_question

PROFILE = {
    "phone": "(425) 336-9852",
    "phoneCountryCode": "+1",
    "phoneDeviceType": "Mobile",
    "country": "United States",
    "marketingConsent": "No",
}

PHONE_CODES = [
    "Canada (+1)",
    "India (+91)",
    "United States Minor Outlying Islands (+1)",
    "United States of America (+1)",
    "United Kingdom (+44)",
]


def _in_chromium(html: str, check):
    async def go():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content(html)
                return await check(page)
            finally:
                await browser.close()

    return asyncio.run(go())


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Phone Device Type", QuestionType.PHONE_DEVICE_TYPE),
        ("Country Phone Code *", QuestionType.PHONE_COUNTRY),
        ("Source *", QuestionType.HOW_HEARD),
        ("Open source contributions", QuestionType.UNKNOWN),
        (
            "Yes, please also add me to Mastercard\u2019s Talent Community, where Mastercard will "
            "send me personalized communications about other job opportunities",
            QuestionType.MARKETING_CONSENT,
        ),
    ],
)
def test_phenom_labels_classify(label, expected):
    assert classify_question(label) == expected


def test_phenom_source_field_id_is_the_referral_question():
    assert classify_question("Source *", "applicantSource") == QuestionType.HOW_HEARD


def test_country_phone_code_picks_the_country_with_its_dial_code():
    res = resolve_answer("Country Phone Code *", PROFILE, options=PHONE_CODES)
    assert res.answer == "United States of America (+1)"


def test_phone_device_type_comes_from_the_profile():
    res = resolve_answer("Phone Device Type", PROFILE, options=["Landline", "Mobile", "Other"])
    assert res.answer == "Mobile"


def test_phone_extension_is_left_blank():
    assert not resolve_answer("Phone Extension", PROFILE).answer


def test_phone_answer_pairs_with_the_number_field_not_the_device_type():
    by_label = {
        "phone device type": {"id": "deviceType"},
        "phone number\n*": {"id": "phoneWidget.phoneNumber"},
    }
    assert _match_dom_field("phone", "", {}, by_label)["id"] == "phoneWidget.phoneNumber"


def test_portal_prefill_is_replaced_only_when_it_disagrees():
    assert _prefill_disagrees("Github, Portfolio", "13310 306th St")
    assert not _prefill_disagrees("13310 306th St", "13310 306th St")
    assert not _prefill_disagrees("98092", "98092")
    assert not _prefill_disagrees("anything", "")


def test_verifier_reads_a_select_by_its_option_text():
    html = """<form>
      <label for="region">State</label>
      <select id="region"><option value="">Please Select</option>
        <option value="USA-WA" selected>Washington</option></select>
      <label for="src">How did you hear?</label>
      <select id="src"><option value="" selected>Please Select</option>
        <option value="APPLICANT_SOURCE-3-12">Careers Site</option></select>
    </form>"""

    async def check(page):
        return (await verify_browser_dom_state(page, [], {})).dom_values

    values = _in_chromium(html, check)
    assert values["State"] == "Washington"
    assert values["How did you hear?"] == ""


def test_independent_consents_sharing_a_fieldset_are_not_a_choice_group():
    html = """<form><fieldset>
      <label><input type="checkbox" id="emailAgreement" required><span>*</span>
        <span>By checking this box, I consent to receive transactional email messages
        regarding employment opportunities at Regions.</span></label>
      <label><input type="checkbox" id="smsOptIn"><span>By checking this box, I consent
        to receive text messages regarding employment opportunities at Regions.</span></label>
    </fieldset></form>"""

    async def check(page):
        return await _is_choice_group_checkbox(page.locator("#emailAgreement"))

    assert _in_chromium(html, check) is False


EDUCATION = [
    {"school": "Santa Clara University", "degree": "Master's Degree", "discipline": "Computer Science"},
    {"school": "Pune Institute of Computer Technology", "degree": "Bachelor's Degree", "discipline": "Computer Science"},
]
EBAY_DEGREES = [
    "Associates Degree or Equivalent", "BSCS or BSEE or Other Related 4yr Technical Degree",
    "Bachelors Degree or Equivalent", "Doctorate or Equivalent", "MBA or Equivalent",
    "Masters Degree or Equivalent", "Other",
]


def test_each_education_row_gets_its_own_degree_over_a_saved_answer():
    profile = {
        "education": EDUCATION,
        "screeningAnswers": [{"id": "d", "question": "Degree", "answer": "Master's Degree", "matchPatterns": ["degree"]}],
    }
    master = resolve_answer("Degree *", profile, options=EBAY_DEGREES, field_id="degree--0")
    bachelor = resolve_answer("Degree *", profile, options=EBAY_DEGREES, field_id="degree--1")
    assert master.answer == "Masters Degree or Equivalent"
    assert bachelor.answer == "Bachelors Degree or Equivalent"


def test_phenom_education_row_maps_by_school_not_row_order():
    html = """<input name="educationData[0].schoolName" value="Pune Institute of Computer Technology">
              <input name="educationData[1].schoolName" value="Santa Clara University">
              <input name="educationData[2].schoolName" value="Some Bootcamp">"""

    async def check(page):
        out = []
        for sel_id in ("educationData[0].degree", "educationData[1].degree", "educationData[2].degree"):
            out.append(await _phenom_education_row_id(page, _PHENOM_EDUCATION_ID.match(sel_id), {"education": EDUCATION}))
        return out

    assert _in_chromium(html, check) == ["degree--1", "degree--0", None]


def test_short_saved_wordings_match_only_the_whole_label():
    import re

    school = _wording_pattern("School")
    assert re.search(school, "school*")
    assert not re.search(school, "how did you perform in mathematics at high school?*")
    long = _wording_pattern("What is your time zone?")
    assert re.search(long, "what is your time zone?* (required)")


def test_spelled_out_age_question_is_the_legal_age_question():
    assert classify_question("Are you at least eighteen (18) years of age?*") == QuestionType.LEGAL_AGE


def test_phenom_apply_urls_and_step_names():
    url = "https://jobs.ebayinc.com/us/en/apply?jobSeqNo=EBAY123&step=3&stepname=jobSpecificQuestions"
    assert _is_phenom_apply_url(url)
    assert _phenom_step_name(url) == "jobSpecificQuestions"
    assert not _is_phenom_apply_url("https://job-boards.greenhouse.io/acme/jobs/1")


def test_radio_group_label_skips_the_page_wide_fieldset():
    html = """<form><fieldset><legend>You are applying for -</legend>
      <input name="cntryFields.firstName">
      <div class="question"><div>Have you ever worked for Mastercard as an employee?</div>
        <label><span><input type="radio" name="previousworker" id="previousworker.Yes" value="Yes"><span>Yes</span></span></label>
        <label><span><input type="radio" name="previousworker" id="previousworker.No" value="No"><span>No</span></span></label>
      </div></fieldset></form>"""

    async def check(page):
        return await page.locator('[id="previousworker.Yes"]').evaluate(_RADIO_GROUP_LABEL_JS)

    assert _in_chromium(html, check) == "Have you ever worked for Mastercard as an employee?"


def test_email_alias_is_dropped_only_when_present():
    html = """<input type="email" id="e" value="candidate+career@example.com">"""

    async def check(page):
        first = await _drop_email_alias(page)
        second = await _drop_email_alias(page)
        return first, second, await page.locator("#e").input_value()

    assert _in_chromium(html, check) == (True, False, "candidate@example.com")


def test_a_box_under_an_overlay_still_gets_ticked():
    html = """<div style="position:relative">
      <input type="checkbox" id="c" style="width:18px;height:18px">
      <div style="position:absolute;inset:0;width:40px;height:40px;z-index:9"></div>
    </div>"""

    async def check(page):
        return await _tick_checkbox(page.locator("#c"))

    assert _in_chromium(html, check) is True
