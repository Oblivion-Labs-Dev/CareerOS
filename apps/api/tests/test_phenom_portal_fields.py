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
    _dismiss_notice_dialog,
    _dismiss_notice_dialog,
    _drop_email_alias,
    _phone_digits_only,
    _phone_digits_only,
    _is_choice_group_checkbox,
    _is_phenom_apply_url,
    _phenom_education_row_id,
    _PHENOM_EDUCATION_ID,
    _phenom_step_name,
    _prefill_disagrees,
    _select_radio_option,
    _shorten_to_limit,
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


def test_overlong_prefill_is_cut_at_a_line_or_sentence_boundary():
    lines = "\n".join(f"Built service {i} handling payments at scale." for i in range(80))
    short = _shorten_to_limit(lines, 2000)
    assert len(short) <= 2000
    assert short.endswith("at scale.")
    assert _shorten_to_limit("short text", 2000) == "short text"
    prose = "Led the platform team. " * 120
    cut = _shorten_to_limit(prose, 2000)
    assert len(cut) <= 2000 and cut.endswith("team.")


@pytest.mark.parametrize("placeholder", ["Select", "Please Select", "Select an option", "-- Select --", "Choose one", ""])
def test_a_select_placeholder_does_not_turn_a_years_yes_into_no(placeholder):
    from app.services.application_assistant.profile_answer_resolver import resolve_answer

    r = resolve_answer(
        "Do you have 4 - 7 years experience in software development, information systems, or equivalent?",
        {"yearsExperience": 9},
        options=[placeholder, "Yes", "No"],
    )
    assert r.answer == "Yes"


MASTERCARD_RADIO = """
<div class="field-radio-group" id="previousworker" role="radiogroup">
  <div class="radio"><label id="previousworker-Yes-label"><span>
    <input type="radio" name="previousworker" id="previousworker.Yes" value="Yes">
    <span class="radio-text">Yes</span></span></label></div>
  <div class="radio"><label id="previousworker-No-label"><span>
    <input type="radio" name="previousworker" id="previousworker.No" value="No">
    <span class="radio-text">No</span></span></label></div>
</div>
"""


def test_a_radio_whose_id_holds_a_dot_is_still_chosen():
    async def check(page):
        chosen = await _select_radio_option(page, "previousworker.Yes", "No")
        return chosen, await page.is_checked('[id="previousworker.No"]'), await page.is_checked('[id="previousworker.Yes"]')

    assert _in_chromium(MASTERCARD_RADIO, check) == (True, True, False)


def test_a_rejected_phone_format_is_refilled_as_digits_but_extensions_are_left():
    html = """<input type="tel" id="cellPhone" value="(425) 336-9852">
              <input type="text" id="phoneExtension" value="12">"""

    async def check(page):
        changed = await _phone_digits_only(page)
        return changed, await page.input_value("#cellPhone"), await page.input_value("#phoneExtension")

    assert _in_chromium(html, check) == (True, "4253369852", "12")


def test_a_success_notice_is_dismissed_but_other_dialogs_are_not():
    html = """<div role="dialog" id="d1"><p>Your Resume Uploaded Successfully.</p>
              <button onclick="document.getElementById('d1').style.display='none'">OK</button></div>
              <div role="dialog" id="d2"><p>Are you sure you want to withdraw?</p>
              <button onclick="document.getElementById('d2').style.display='none'">OK</button></div>"""

    async def check(page):
        await _dismiss_notice_dialog(page)
        return await page.is_visible("#d1"), await page.is_visible("#d2")

    assert _in_chromium(html, check) == (False, True)


def test_a_rejected_phone_format_is_refilled_as_digits_but_extensions_are_left():
    html = """<input type="tel" id="cellPhone" value="(425) 336-9852">
              <input type="text" id="phoneExtension" value="12">"""

    async def check(page):
        changed = await _phone_digits_only(page)
        return changed, await page.input_value("#cellPhone"), await page.input_value("#phoneExtension")

    assert _in_chromium(html, check) == (True, "4253369852", "12")


def test_a_success_notice_is_dismissed_but_other_dialogs_are_not():
    html = """<div role="dialog" id="d1"><p>Your Resume Uploaded Successfully.</p>
              <button onclick="document.getElementById('d1').style.display='none'">OK</button></div>
              <div role="dialog" id="d2"><p>Are you sure you want to withdraw?</p>
              <button onclick="document.getElementById('d2').style.display='none'">OK</button></div>"""

    async def check(page):
        await _dismiss_notice_dialog(page)
        return await page.is_visible("#d1"), await page.is_visible("#d2")

    assert _in_chromium(html, check) == (False, True)


def test_descriptive_words_in_a_years_question_are_not_read_as_technologies():
    r = resolve_answer(
        "Do you have 4 - 7 years experience in software development, information systems, or equivalent "
        "technical environment, including experience in development of highly transactional, mission "
        "critical, multi-user architectures?",
        {"yearsExperience": 9},
        options=["Please Select", "Yes", "No"],
        field_id="secondaryJsqData.QUESTIONNAIRE-3-5727.a",
    )
    assert r.answer == "Yes" and not r.blocking_errors


def test_in_your_current_role_do_you_is_a_yes_no_question_not_a_job_title():
    q = "In your current role, do you engage with Mastercard employees to negotiate, influence and/or sign commercial contracts?"
    assert classify_question(q) != QuestionType.CURRENT_TITLE
    assert classify_question("What is your current role?") == QuestionType.CURRENT_TITLE


COMBINED_RACE_OPTIONS = [
    "American Indian or Alaska Native (Not Hispanic or Latino) (United States of America)",
    "Asian (Not Hispanic or Latino) (United States of America)",
    "Black or African American (Not Hispanic or Latino) (United States of America)",
    "Hispanic or Latino (United States of America)",
    "Prefer Not to Self-Identify (United States of America)",
    "White (Not Hispanic or Latino) (United States of America)",
]


def test_combined_race_ethnicity_list_picks_the_profile_race_not_the_decline():
    r = resolve_answer(
        "Please enter your race/ethnicity.*",
        {"raceEthnicity": "Asian", "raceEthnicitySpecific": "Indian", "hispanic": "No"},
        options=["Please Select", *COMBINED_RACE_OPTIONS],
    )
    assert r.answer == "Asian (Not Hispanic or Latino) (United States of America)"


def test_a_text_answer_that_no_yes_no_option_can_take_is_dropped():
    r = resolve_answer(
        "Have you ever been employed by an organization (company/agency) that is a Fiserv or First Data client/customer?",
        {"currentCompany": "Microsoft", "workExperience": [{"company": "Microsoft", "current": True}]},
        options=["Please Select", "Yes", "No"],
    )
    assert r.answer != "Microsoft"


def test_willingness_to_sign_a_non_compete_is_not_defaulted_to_no():
    r = resolve_answer("Are you willing to sign a non-compete agreement?", {}, options=["Yes", "No"])
    assert not r.answer


EBAY_DISABILITY = """
<div class="field-radio-group" id="disability_heading_self_identity.disabilityStatus" role="radiogroup">
  <div class="radio"><label><span><input type="radio" name="disability_heading_self_identity.disabilityStatus"
    id="disability_heading_self_identity.disabilityStatus.YES_REV_2026" value="YES_REV_2026">
    <span class="radio-text">Yes, I have a disability, or have had one in the past</span></span></label></div>
  <div class="radio"><label><span><input type="radio" name="disability_heading_self_identity.disabilityStatus"
    id="disability_heading_self_identity.disabilityStatus.NO_REV_2026" value="NO_REV_2026">
    <span class="radio-text">No, I do not have a disability and have not had one in the past</span></span></label></div>
</div>
"""


def test_a_radio_coded_in_its_value_is_chosen_by_its_wrapping_label():
    async def check(page):
        chosen = await _select_radio_option(
            page, "disability_heading_self_identity.disabilityStatus.YES_REV_2026",
            "No, I do not have a disability and have not had one in the past",
        )
        return chosen, await page.is_checked('[id="disability_heading_self_identity.disabilityStatus.NO_REV_2026"]')

    assert _in_chromium(EBAY_DISABILITY, check) == (True, True)


EBAY_DISABILITY_FORM = """
<div class="row form-group field disability-status-radio" role="radiogroup" aria-labelledby="dis-head" aria-required="true">
  <label class="control-label" id="dis-head"><b>Please check one of the boxes below:</b><span class="required">*</span></label>
""" + EBAY_DISABILITY + "</div>"


def test_verifier_reads_a_phenom_radio_group_by_its_question_and_option_text():
    from app.services.application_assistant.profile_answer_resolver import AnswerResolution

    async def check(page):
        await page.check('[id="disability_heading_self_identity.disabilityStatus.NO_REV_2026"]')
        res = AnswerResolution(
            field_id="disability_heading_self_identity.disabilityStatus.YES_REV_2026",
            question="Please check one of the boxes below:",
            question_type="DISABILITY",
            answer="No, I do not have a disability and have not had one in the past",
        )
        result = await verify_browser_dom_state(page, [res], {})
        return [(i.issue_type, i.label) for i in result.issues]

    assert _in_chromium(EBAY_DISABILITY_FORM, check) == []


def _fiserv_military(required: bool) -> str:
    star = " *" if required else ""
    boxes = "".join(
        f'<div class="checkbox"><label><span><input type="checkbox" id="jsqData.QUESTIONNAIRE-6-818.i_{i}" '
        f'aria-label="{text}" value="QUESTION_MULTIPLE_CHOICE_ANSWER-6-{2288 + i}"><span>{text}</span></span></label></div>'
        for i, text in enumerate([
            "United States Military Veteran",
            "Currently serving in the United States Guard or Reserves",
            "Military Spouse (current or former)",
            "No, or I prefer not to identify",
        ])
    )
    return (
        '<form><div class="form-group"><label for="jsqData.QUESTIONNAIRE-6-818.i">Are you a current or former United '
        f'States Military Service Member or military spouse? (Please select all that apply){star}</label>'
        f'<div class="checkboxes" id="jsqData.QUESTIONNAIRE-6-818.i">{boxes}</div></div></form>'
    )


@pytest.mark.parametrize("required", [True, False])
def test_phenom_checkbox_group_takes_the_profile_answer_only_when_required(required):
    from app.services.application_assistant.playwright_autopilot_executor import _fill_standard_and_react_fields

    async def check(page):
        await _fill_standard_and_react_fields(page, {"veteran": "I am not a protected veteran"}, None, "Fiserv", "x", "")
        return [await page.is_checked(f'[id="jsqData.QUESTIONNAIRE-6-818.i_{i}"]') for i in range(4)]

    assert _in_chromium(_fiserv_military(required), check) == ([False, False, False, required])
