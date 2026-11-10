"""Regression: a Lever multiple-choice card rendered as checkboxes gets its answer ticked.

Seen live on Lever (Spotify, 2026-11-05): "Have you ever been previously
employed by Spotify?" is a <ul data-qa="checkboxes"> of boxes sharing one name
(No / Yes - Intern / Yes - Full Time Employment) with no fieldset or legend.
The resolver answered "No", but no checkbox pass saw the group, so the
required field stayed empty and the job went to review.
"""
from __future__ import annotations

from app.services.application_assistant.playwright_autopilot_executor import _fill_lever_checkbox_groups
from tests.browser_test_utils import eval_in_pooled_page

_HTML = """
<ul>
<li class="application-question custom-question">
  <div class="application-label full-width"><div class="text">Have you ever been previously employed by Spotify?<span class="required">✱</span></div></div>
  <div class="application-field full-width">
    <ul data-qa="checkboxes">
      <li><label><input type="checkbox" name="cards[abc][field0]" value="No"><span class="application-answer-alternative">No</span></label></li>
      <li><label><input type="checkbox" name="cards[abc][field0]" value="Yes - Intern"><span class="application-answer-alternative">Yes - Intern</span></label></li>
      <li><label><input type="checkbox" name="cards[abc][field0]" value="Yes - Full Time Employment"><span class="application-answer-alternative">Yes - Full Time Employment</span></label></li>
    </ul>
  </div>
</li>
</ul>
"""


def test_lever_checkbox_card_ticks_only_the_resolved_option():
    async def check(page):
        filled: dict = {}
        await _fill_lever_checkbox_groups(page, {"workHistory": [{"company": "Acme"}]}, None, filled, {})
        ticked = await page.eval_on_selector_all("input[type=checkbox]", "els => els.filter(e => e.checked).map(e => e.value)")
        return ticked, list(filled.values())

    assert eval_in_pooled_page(_HTML, check) == (["No"], ["No"])


def test_lever_checkbox_card_already_answered_is_left_alone():
    html = _HTML.replace('value="Yes - Intern">', 'value="Yes - Intern" checked>')

    async def check(page):
        filled: dict = {}
        await _fill_lever_checkbox_groups(page, {}, None, filled, {})
        ticked = await page.eval_on_selector_all("input[type=checkbox]", "els => els.filter(e => e.checked).map(e => e.value)")
        return ticked, filled

    assert eval_in_pooled_page(html, check) == (["Yes - Intern"], {})
